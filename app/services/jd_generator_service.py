"""Job Description Generator Service — AI-powered dynamic JD generation.

Generates structured, production-grade, ATS-optimized job descriptions from recruiter input.
Strictly respects recruiter-provided skills, experience constraints, company context,
and provides multi-provider LLM inference with deterministic fallback generation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.exceptions import AppException
from app.llm.client import get_llm_client
from app.llm.response_parser import ResponseParser
from app.schemas.recruitment import (
    JobDescriptionExperienceSchema,
    JobDescriptionStructuredRequest,
    JobDescriptionStructuredResponse,
)

logger = logging.getLogger(__name__)

CANONICAL_SKILL_MAP: dict[str, str] = {
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "react js": "React",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "python": "Python",
    "py": "Python",
    "python3": "Python",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "fastapi": "FastAPI",
    "fast api": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "express": "Express.js",
    "expressjs": "Express.js",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "postgre": "PostgreSQL",
    "docker": "Docker",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "Google Cloud (GCP)",
    "google cloud": "Google Cloud (GCP)",
    "azure": "Microsoft Azure",
    "microsoft azure": "Microsoft Azure",
    "graphql": "GraphQL",
    "rest": "REST APIs",
    "restful": "REST APIs",
    "rest api": "REST APIs",
    "git": "Git",
    "github": "GitHub",
    "gitlab": "GitLab",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "sql": "SQL",
    "nosql": "NoSQL",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "angular": "Angular",
    "angularjs": "Angular",
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "golang": "Go",
    "go": "Go",
    "java": "Java",
    "spring": "Spring Boot",
    "springboot": "Spring Boot",
    "terraform": "Terraform",
    "kafka": "Apache Kafka",
    "spark": "Apache Spark",
    "tailwind": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "redux": "Redux",
    "html": "HTML5",
    "css": "CSS3",
    "sass": "SASS/SCSS",
    "scss": "SASS/SCSS",
    "jira": "Jira",
    "linux": "Linux",
}

_SYSTEM_PROMPT = """You are an elite talent acquisition partner and compensation architect for enterprise ATS platforms.
Your role is to generate a comprehensive, highly professional, ATS-optimized, and structured Job Description (JD) based strictly on recruiter specifications.

CRITICAL ACCURACY & INTEGRITY RULES:
1. REQUIRED SKILLS: Include ALL recruiter-supplied required skills explicitly. Do not drop any required skill.
2. PREFERRED SKILLS: Provide 3-5 complementary nice-to-have skills. Never convert preferred skills into mandatory requirements.
3. EXPERIENCE FIDELITY: Strictly adhere to the requested years of experience. Never invent conflicting experience requirements (for example, if 3–6 years is specified, do NOT write 5+ years or 7+ years).
4. RESTRAIN HALLUCINATIONS: Do NOT invent confidential company policies, exact non-provided salaries, or unsupported certifications. If optional information is missing, infer reasonable industry-standard defaults.
5. ATS OPTIMIZATION: Include high-intent, role-specific search keywords in a natural, un-stuffed manner.
6. JSON ONLY: Output MUST be strictly valid JSON matching the exact schema requested. No markdown wrappers or preamble outside the JSON."""


class CacheEntry:
    def __init__(self, data: dict[str, Any], ttl_seconds: float = 600.0) -> None:
        self.data = data
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class JDGeneratorService:
    """AI Service for dynamic, production-grade Job Description generation."""

    _instance: Optional[JDGeneratorService] = None

    def __init__(self) -> None:
        self.llm = get_llm_client()
        self._cache: Dict[str, CacheEntry] = {}
        self._in_flight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> JDGeneratorService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def normalize_skill(skill: str) -> str:
        """Normalize a skill name to canonical title casing or standard notation."""
        s = skill.strip()
        lower = s.lower()
        if lower in CANONICAL_SKILL_MAP:
            return CANONICAL_SKILL_MAP[lower]
        # Preserve capitalization if already PascalCase/UPPERCASE, else Title Case
        if any(c.isupper() for c in s[1:]):
            return s
        return s.capitalize()

    @classmethod
    def normalize_skill_list(cls, skills: list[str]) -> list[str]:
        """Normalize and deduplicate a list of skill strings."""
        result: list[str] = []
        seen = set()
        for raw in skills:
            if not raw:
                continue
            for item in str(raw).split(","):
                norm = cls.normalize_skill(item)
                if norm and norm.lower() not in seen:
                    seen.add(norm.lower())
                    result.append(norm)
        return result

    def _generate_cache_key(self, payload: JobDescriptionStructuredRequest) -> str:
        """Generate deterministic cache key for in-flight deduplication and caching."""
        key_data = {
            "title": payload.job_title.lower().strip(),
            "skills": sorted([s.lower() for s in payload.skills]),
            "location": payload.location.lower().strip(),
            "exp_min": payload.experience_min,
            "exp_max": payload.experience_max,
            "emp_type": payload.employment_type.lower().strip(),
            "dept": payload.department.lower().strip(),
            "tone": payload.tone.lower().strip(),
            "length": payload.length.lower().strip(),
            "work_mode": (payload.work_mode or "").lower().strip(),
            "company": (payload.company_name or "").lower().strip(),
        }
        raw_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

    async def generate_structured_jd(
        self,
        payload: JobDescriptionStructuredRequest,
        company_context: Optional[dict[str, Any]] = None,
    ) -> JobDescriptionStructuredResponse:
        """Generate structured, recruiter-editable Job Description."""
        # Clean and normalize input skills
        normalized_skills = self.normalize_skill_list(payload.skills)
        payload.skills = normalized_skills or ["General Skills"]

        company_name = payload.company_name
        industry = payload.industry or "Technology"
        if company_context:
            company_name = company_name or company_context.get("name") or company_context.get("company_name")
            industry = industry or company_context.get("industry") or "Technology"
        company_name = company_name or "Our Organization"

        cache_key = self._generate_cache_key(payload)

        # 1. Check TTL Cache
        if cache_key in self._cache and not self._cache[cache_key].is_expired:
            logger.info("AI JD Generation CACHE HIT | title='%s' | key=%s", payload.job_title, cache_key[:8])
            return JobDescriptionStructuredResponse(**self._cache[cache_key].data)

        # 2. In-flight request deduplication
        future_to_await = None
        async with self._lock:
            if cache_key in self._cache and not self._cache[cache_key].is_expired:
                return JobDescriptionStructuredResponse(**self._cache[cache_key].data)

            if cache_key in self._in_flight:
                logger.info("AI JD Generation DEDUPLICATING in-flight request | title='%s'", payload.job_title)
                future_to_await = self._in_flight[cache_key]
            else:
                loop = asyncio.get_running_loop()
                future_to_await = loop.create_future()
                self._in_flight[cache_key] = future_to_await
                is_leader = True

        if "is_leader" not in locals():
            raw_dict = await future_to_await
            return JobDescriptionStructuredResponse(**raw_dict)

        # 3. Perform AI Generation
        start_time = time.perf_counter()
        logger.info(
            "START AI JD Generation | title='%s' | dept='%s' | exp_min=%.1f | exp_max=%s | skills=%s",
            payload.job_title,
            payload.department,
            payload.experience_min,
            payload.experience_max,
            normalized_skills,
        )

        try:
            result_dict = await self._generate_from_llm(payload, company_name, industry)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info("SUCCESS AI JD Generation | title='%s' | elapsed=%.1fms", payload.job_title, elapsed_ms)

            self._cache[cache_key] = CacheEntry(result_dict, ttl_seconds=600.0)
            if not future_to_await.done():
                future_to_await.set_result(result_dict)
            return JobDescriptionStructuredResponse(**result_dict)

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(
                "AI JD Generation LLM Exception (falling back to structured generator) | err=%s | elapsed=%.1fms",
                exc,
                elapsed_ms,
            )
            fallback_dict = self._build_structured_fallback(payload, company_name, industry)
            self._cache[cache_key] = CacheEntry(fallback_dict, ttl_seconds=300.0)
            if not future_to_await.done():
                future_to_await.set_result(fallback_dict)
            return JobDescriptionStructuredResponse(**fallback_dict)

        finally:
            async with self._lock:
                self._in_flight.pop(cache_key, None)

    async def _generate_from_llm(
        self,
        payload: JobDescriptionStructuredRequest,
        company_name: str,
        industry: str,
    ) -> dict[str, Any]:
        """Call multi-provider LLM to generate structured JD."""
        skills_str = ", ".join(payload.skills)
        if payload.experience_max and payload.experience_max > payload.experience_min:
            exp_str = f"{int(payload.experience_min)}–{int(payload.experience_max)} years"
        elif payload.experience_min > 0:
            exp_str = f"{int(payload.experience_min)}+ years"
        else:
            exp_str = payload.experience or "Entry level / 0-1 years"

        salary_section = ""
        if payload.salary_min or payload.salary_max:
            salary_section = f"\n- Salary Budget: {payload.currency or 'USD'} {payload.salary_min or 0} - {payload.salary_max or 0}"

        seniority_section = f"\n- Seniority Level: {payload.seniority_level}" if payload.seniority_level else ""
        education_section = f"\n- Education Preference: {payload.education}" if payload.education else ""
        additional_section = f"\n- Recruiter Instructions: {payload.additional_requirements}" if payload.additional_requirements else ""

        length_guide = {
            "short": "Concise (3-4 bullet points per section)",
            "standard": "Standard (5-7 bullet points per section)",
            "detailed": "Comprehensive and detailed (7-9 bullet points per section)",
        }.get(payload.length.lower(), "Standard (5-7 bullet points per section)")

        prompt = f"""Generate a structured, professional, ATS-optimized Job Description strictly based on these specifications:
- Job Title: {payload.job_title}
- Department: {payload.department}
- Employment Type: {payload.employment_type}
- Work Mode: {payload.work_mode or 'Remote'}
- Location: {payload.location}
- Required Skills: {skills_str}
- Experience Requirement: {exp_str}{seniority_section}{salary_section}{education_section}{additional_section}
- Company Name: {company_name}
- Industry: {industry}
- Desired Tone: {payload.tone} (e.g. Professional, Startup, Corporate, Technical)
- Target Length: {length_guide}

Return ONLY a strict JSON object matching this EXACT structure:
{{
  "title": "{payload.job_title}",
  "summary": "2-3 compelling sentences describing the mission of this role at {company_name}.",
  "about_role": "Detailed overview of the day-to-day impact, team culture, and objectives.",
  "responsibilities": [
    "Action-oriented responsibility bullet points starting with strong verbs"
  ],
  "required_skills": {json.dumps(payload.skills)},
  "preferred_skills": [
    "3-5 inferred nice-to-have skills that complement the required skills"
  ],
  "experience": {{
    "min_years": {payload.experience_min},
    "max_years": {json.dumps(payload.experience_max)},
    "text": "{exp_str}"
  }},
  "education": [
    "Relevant degree or practical equivalent requirement"
  ],
  "qualifications": [
    "Core professional and technical qualifications"
  ],
  "nice_to_have": [
    "Bonus certifications, domain exposure, or architectural experience"
  ],
  "benefits": [
    "Modern compensation, healthcare, flexibility, and growth perks"
  ],
  "location": "{payload.location}",
  "work_mode": "{payload.work_mode or 'Remote'}",
  "employment_type": "{payload.employment_type}",
  "department": "{payload.department}",
  "seniority_level": {json.dumps(payload.seniority_level)},
  "ats_keywords": [
    "High-intent ATS keywords, tools, frameworks, and domain phrases"
  ],
  "suggested_salary_range": {{
    "currency": "{payload.currency or 'USD'}",
    "min": {payload.salary_min or 'null'},
    "max": {payload.salary_max or 'null'}
  }},
  "hiring_process_steps": [
    "Initial Application & Screening",
    "Technical Assessment / Coding Discussion",
    "System Design & Team Alignment",
    "Final Cultural & Offer Conversation"
  ]
}}"""

        raw_response = await self.llm.complete(
            prompt=prompt,
            system=_SYSTEM_PROMPT,
            json_mode=True,
            temperature=0.3,
            num_predict=2048,
        )

        parsed = ResponseParser.extract_json_object(raw_response)
        if not parsed or not isinstance(parsed, dict) or "title" not in parsed:
            raise ValueError(f"LLM returned invalid JSON structure: {raw_response[:200]}")

        # Post-process and guarantee strict fields
        return self._normalize_generated_dict(parsed, payload, company_name, exp_str, is_ai=True)

    def _normalize_generated_dict(
        self,
        data: dict[str, Any],
        payload: JobDescriptionStructuredRequest,
        company_name: str,
        exp_str: str,
        is_ai: bool = True,
    ) -> dict[str, Any]:
        """Sanitize and validate extracted dictionary to guarantee complete compliance with schema."""
        title = str(data.get("title") or payload.job_title).strip()
        summary = str(data.get("summary") or "").strip()
        if not summary:
            summary = f"We are seeking an exceptional {title} to join our {payload.department} team at {company_name}."

        about_role = str(data.get("about_role") or "").strip()
        if not about_role:
            about_role = f"As a {title}, you will drive core technical initiatives, collaborate across multidisciplinary teams, and deliver robust solutions in a fast-paced environment."

        # Guarantee responsibilities list
        raw_resp = data.get("responsibilities") or data.get("key_responsibilities") or []
        if isinstance(raw_resp, str):
            raw_resp = [r.strip("- ") for r in raw_resp.split("\n") if r.strip()]
        responsibilities = [str(r).strip() for r in raw_resp if str(r).strip()]
        if not responsibilities:
            responsibilities = [
                f"Design, build, and deliver high-performance solutions for {title} workflows",
                f"Collaborate with product, engineering, and cross-functional teams",
                "Uphold high standards for code quality, architectural integrity, and automated testing",
                "Participate in technical reviews, sprint planning, and mentorship",
            ]

        # Guarantee required skills contains all recruiter skills
        ai_req = self.normalize_skill_list(data.get("required_skills") or [])
        merged_req = list(payload.skills)
        for s in ai_req:
            if s and s.lower() not in [x.lower() for x in merged_req]:
                merged_req.append(s)

        # Guarantee preferred skills
        raw_pref = data.get("preferred_skills") or data.get("preferred_qualifications") or []
        if isinstance(raw_pref, str):
            raw_pref = [p.strip("- ") for p in raw_pref.split("\n") if p.strip()]
        pref_norm = self.normalize_skill_list(raw_pref)
        preferred_skills = [p for p in pref_norm if p.lower() not in [r.lower() for r in merged_req]]
        if not preferred_skills:
            preferred_skills = ["Agile/Scrum Methodologies", "Cloud CI/CD Pipelines", "Automated Testing Frameworks"]

        # Experience structure
        exp_dict = {
            "min_years": float(payload.experience_min),
            "max_years": float(payload.experience_max) if payload.experience_max is not None else None,
            "text": exp_str,
        }

        # Education
        education = data.get("education") or []
        if isinstance(education, str):
            education = [education]
        if not education:
            education = ["Bachelor's degree in Computer Science, Engineering, or equivalent practical experience"]

        # Qualifications
        qualifications = data.get("qualifications") or data.get("requirements") or []
        if isinstance(qualifications, str):
            qualifications = [q.strip("- ") for q in qualifications.split("\n") if q.strip()]
        if not qualifications:
            qualifications = [
                f"{exp_str} of relevant professional experience in a related capacity",
                f"Demonstrated proficiency in {', '.join(merged_req[:3])}",
                "Strong analytical, collaborative, and problem-solving abilities",
            ]

        # Nice to have
        nice_to_have = data.get("nice_to_have") or preferred_skills[:3]
        if isinstance(nice_to_have, str):
            nice_to_have = [nice_to_have]

        # Benefits
        benefits = data.get("benefits") or data.get("benefits_and_perks") or []
        if isinstance(benefits, str):
            benefits = [b.strip("- ") for b in benefits.split("\n") if b.strip()]
        if not benefits:
            benefits = [
                "Competitive base compensation and performance incentives",
                "Comprehensive medical, dental, and wellness coverage",
                "Flexible working arrangements and paid time off",
                "Professional growth and learning stipend",
            ]

        # ATS Keywords
        ats_keywords = data.get("ats_keywords") or []
        if not ats_keywords:
            ats_keywords = list(dict.fromkeys(merged_req + [title, payload.department, "Problem Solving", "Collaboration"]))

        # Suggested Salary
        suggested_salary = data.get("suggested_salary_range")
        if not suggested_salary or not isinstance(suggested_salary, dict):
            if payload.salary_min or payload.salary_max:
                suggested_salary = {
                    "currency": payload.currency or "USD",
                    "min": payload.salary_min,
                    "max": payload.salary_max,
                }
            else:
                suggested_salary = None

        # Steps
        steps = data.get("hiring_process_steps") or [
            "Resume Screening & Profile Evaluation",
            "Technical Assessment & Skill Evaluation",
            "Team Collaboration & Domain Interview",
            "Final Discussion & Offer Decision",
        ]

        metadata = {
            "ai_generated": is_ai,
            "fallback_generated": not is_ai,
            "ai_model": getattr(self.llm, "default_model", "unified-llm-router"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tone": payload.tone,
            "length": payload.length,
        }

        return {
            "title": title,
            "summary": summary,
            "about_role": about_role,
            "responsibilities": responsibilities,
            "required_skills": merged_req,
            "preferred_skills": preferred_skills,
            "experience": exp_dict,
            "education": education,
            "qualifications": qualifications,
            "nice_to_have": nice_to_have,
            "benefits": benefits,
            "location": payload.location,
            "work_mode": payload.work_mode or "Remote",
            "employment_type": payload.employment_type,
            "department": payload.department,
            "seniority_level": payload.seniority_level,
            "ats_keywords": ats_keywords,
            "suggested_salary_range": suggested_salary,
            "hiring_process_steps": steps,
            "metadata": metadata,
        }

    def _build_structured_fallback(
        self,
        payload: JobDescriptionStructuredRequest,
        company_name: str,
        industry: str,
    ) -> dict[str, Any]:
        """Deterministic high-quality fallback generator adhering strictly to recruiter inputs."""
        title = payload.job_title.strip()
        dept = payload.department.strip() or "Engineering"
        loc = payload.location.strip() or "Remote"
        skills = self.normalize_skill_list(payload.skills) or ["Core Domain Expertise"]
        emp_type = payload.employment_type or "Full-time"

        if payload.experience_max and payload.experience_max > payload.experience_min:
            exp_str = f"{int(payload.experience_min)}–{int(payload.experience_max)} years"
        elif payload.experience_min > 0:
            exp_str = f"{int(payload.experience_min)}+ years"
        else:
            exp_str = payload.experience or "Entry level / 0-1 years"

        summary = f"{company_name} is actively seeking a talented and driven {title} with {exp_str} of experience to join our {dept} team."
        about_role = f"In this role as {title}, you will collaborate closely with cross-functional partners in {industry} to design, implement, and maintain high-impact solutions while fostering technical excellence."

        responsibilities = [
            f"Drive execution, design, and delivery of key initiatives for the {title} position",
            f"Apply hands-on expertise in {', '.join(skills[:3])} to build resilient systems and workflows",
            "Collaborate with team members to solve complex challenges and improve operational efficiency",
            "Uphold high standards of code quality, documentation, and automated testing",
            "Participate in sprint planning, architecture discussions, and continuous improvement",
        ]

        # Inferred preferred skills
        inferred_pref = ["Agile Methodologies", "CI/CD & Cloud Deployment", "Microservices Architecture"]
        preferred_skills = [p for p in inferred_pref if p.lower() not in [s.lower() for s in skills]]

        qualifications = [
            f"{exp_str} of proven professional experience in a {title} or closely related role",
            f"Demonstrated technical proficiency with: {', '.join(skills)}",
            "Strong communication, analytical, and collaborative problem-solving abilities",
            "Demonstrated track record of delivering high-quality deliverables in a fast-paced environment",
        ]

        benefits = [
            "Competitive compensation package with performance bonuses",
            "Comprehensive health, medical, and wellness coverage",
            "Flexible remote/hybrid work arrangements and paid time off",
            "Dedicated annual learning and professional growth budget",
        ]

        salary_range = None
        if payload.salary_min or payload.salary_max:
            salary_range = {
                "currency": payload.currency or "USD",
                "min": payload.salary_min,
                "max": payload.salary_max,
            }

        return self._normalize_generated_dict(
            data={
                "title": title,
                "summary": summary,
                "about_role": about_role,
                "responsibilities": responsibilities,
                "required_skills": skills,
                "preferred_skills": preferred_skills,
                "education": [f"Bachelor's degree in relevant discipline or equivalent practical experience"],
                "qualifications": qualifications,
                "nice_to_have": ["Experience in high-growth agile environments", "Domain certifications"],
                "benefits": benefits,
                "suggested_salary_range": salary_range,
            },
            payload=payload,
            company_name=company_name,
            exp_str=exp_str,
            is_ai=False,
        )

    async def modify_job_description(
        self,
        current_jd: dict[str, Any] | str,
        action: str,
        custom_instruction: Optional[str] = None,
    ) -> dict[str, Any] | str:
        """Modify or rewrite job description based on recruiter refinement action."""
        action_clean = action.lower().strip()
        is_dict = isinstance(current_jd, dict)

        action_prompt_map = {
            "improve": "Polish the flow, clarity, and engagement of the job description while preserving all technical details.",
            "expand": "Add more depth and comprehensive details to responsibilities and impact while preserving key requirements.",
            "shorten": "Make the job description more concise and punchy, removing fluff while preserving essential details.",
            "professional": "Adopt an authoritative, formal, and corporate tone suitable for enterprise recruitment.",
            "startup": "Adopt an energetic, mission-driven, and innovative startup tone.",
            "technical": "Emphasize technical rigor, system architecture, engineering metrics, and concrete technical competencies.",
        }
        action_instruction = action_prompt_map.get(action_clean)
        if action_clean == "custom" and custom_instruction:
            action_instruction = f"Apply this specific recruiter instruction: {custom_instruction}"
        elif not action_instruction:
            action_instruction = "Refine and improve the job description."

        if is_dict:
            prompt = f"""You are an expert HR copywriter. Modify the following structured Job Description JSON according to this instruction:
{action_instruction}

Current JD:
{json.dumps(current_jd, indent=2)}

Keep the exact same JSON keys and structure. Return ONLY valid JSON."""
            try:
                raw_resp = await self.llm.complete(
                    prompt=prompt,
                    system=_SYSTEM_PROMPT,
                    json_mode=True,
                    temperature=0.3,
                    num_predict=2048,
                )
                parsed = ResponseParser.extract_json_object(raw_resp)
                if parsed and isinstance(parsed, dict) and "title" in parsed:
                    if "metadata" in parsed:
                        parsed["metadata"]["modified_action"] = action_clean
                    return parsed
            except Exception as e:
                logger.warning("modify_job_description structured failed: %s", e)
            return current_jd

        # Text modification
        prompt = f"""You are an expert HR copywriter. Modify this job description text according to this instruction:
{action_instruction}

Job Description:
{current_jd}

Return ONLY the updated job description text (no conversational preamble)."""
        try:
            raw_resp = await self.llm.complete(
                prompt=prompt,
                system="You are a professional HR writing assistant. Return only updated job description text.",
                temperature=0.3,
                num_predict=2048,
            )
            if raw_resp and len(raw_resp.strip()) > 30:
                return raw_resp.strip()
        except Exception as e:
            logger.warning("modify_job_description text failed: %s", e)

        return current_jd


# Singleton accessor
def get_jd_generator_service() -> JDGeneratorService:
    return JDGeneratorService.get_instance()


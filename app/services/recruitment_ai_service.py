"""
Service for AI-driven Job Description generation and 1-Click Form Auto-fill.
Provides in-flight deduplication, TTL caching, structured logging, robust validation,
and fallback templates to guarantee fast, race-condition-safe response times.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.exceptions import AppException
from app.services.ollama_client import ollama_client

logger = logging.getLogger("app.services.recruitment_ai_service")


class CacheEntry:
    def __init__(self, data: Any, ttl_seconds: float = 600.0):
        self.data = data
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl_seconds


class RecruitmentAIService:
    _instance: Optional[RecruitmentAIService] = None

    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._in_flight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> RecruitmentAIService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _generate_cache_key(self, prefix: str, payload: Dict[str, Any]) -> str:
        sorted_items = sorted((k, str(v).lower().strip()) for k, v in payload.items() if v is not None)
        raw_str = f"{prefix}:" + "&".join(f"{k}={v}" for k, v in sorted_items)
        return hashlib.sha256(raw_str.encode()).hexdigest()

    async def get_or_generate_autofill(
        self,
        title: str,
        experience: Optional[str] = None,
        salary_min: Optional[float] = None,
        salary_max: Optional[float] = None,
        currency: Optional[str] = "USD",
    ) -> Dict[str, Any]:
        title_clean = title.strip()
        if not title_clean:
            raise AppException(message="Job title is required for AI auto-fill.", status_code=422)

        payload_dict = {
            "title": title_clean,
            "experience": experience,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "currency": currency,
        }

        cache_key = self._generate_cache_key("autofill", payload_dict)

        # 1. Check Cache
        if cache_key in self._cache and not self._cache[cache_key].is_expired:
            logger.info("AI Auto-fill CACHE HIT | title='%s' | key=%s", title_clean, cache_key[:10])
            return self._cache[cache_key].data

        # 2. Check In-Flight Task (Deduplication)
        future_to_await = None
        async with self._lock:
            if cache_key in self._cache and not self._cache[cache_key].is_expired:
                return self._cache[cache_key].data

            if cache_key in self._in_flight:
                logger.info("AI Auto-fill DEDUPLICATING in-flight request | title='%s'", title_clean)
                future_to_await = self._in_flight[cache_key]
            else:
                loop = asyncio.get_running_loop()
                future_to_await = loop.create_future()
                self._in_flight[cache_key] = future_to_await
                # Mark that THIS execution is responsible for calculating
                is_leader = True

        if 'is_leader' not in locals():
            return await future_to_await

        # 3. Perform AI Generation
        start_time = time.perf_counter()
        logger.info("START AI Auto-fill Generation | title='%s'", title_clean)

        try:
            result = await self._generate_autofill_from_llm(title_clean, experience, salary_min, salary_max, currency)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info("SUCCESS AI Auto-fill Generation | title='%s' | elapsed=%.1fms", title_clean, elapsed_ms)

            self._cache[cache_key] = CacheEntry(result, ttl_seconds=600.0)
            if not future_to_await.done():
                future_to_await.set_result(result)
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning("AI Auto-fill LLM Exception (using fallback) | err=%s | elapsed=%.1fms", exc, elapsed_ms)
            fallback = self._build_autofill_fallback(title_clean, experience, salary_min, salary_max, currency)
            self._cache[cache_key] = CacheEntry(fallback, ttl_seconds=300.0)
            if not future_to_await.done():
                future_to_await.set_result(fallback)
            return fallback
        finally:
            async with self._lock:
                self._in_flight.pop(cache_key, None)

    async def get_or_generate_description(
        self,
        title: str,
        department: Optional[str] = "Engineering",
        employment_type: Optional[str] = "Full-time",
        location: Optional[str] = "Remote",
        skills: Optional[List[str]] = None,
        experience: Optional[str] = None,
    ) -> str:
        title_clean = title.strip()
        if not title_clean:
            raise AppException(message="Job title is required for AI description generation.", status_code=422)

        payload_dict = {
            "title": title_clean,
            "department": department or "Engineering",
            "employment_type": employment_type or "Full-time",
            "location": location or "Remote",
            "skills": ",".join(skills) if skills else "",
            "experience": experience or "",
        }

        cache_key = self._generate_cache_key("description", payload_dict)

        # 1. Check Cache
        if cache_key in self._cache and not self._cache[cache_key].is_expired:
            logger.info("AI Description CACHE HIT | title='%s'", title_clean)
            return self._cache[cache_key].data

        # 2. Check In-Flight Task (Deduplication)
        future_to_await = None
        async with self._lock:
            if cache_key in self._cache and not self._cache[cache_key].is_expired:
                return self._cache[cache_key].data

            if cache_key in self._in_flight:
                logger.info("AI Description DEDUPLICATING in-flight request | title='%s'", title_clean)
                future_to_await = self._in_flight[cache_key]
            else:
                loop = asyncio.get_running_loop()
                future_to_await = loop.create_future()
                self._in_flight[cache_key] = future_to_await
                is_leader = True

        if 'is_leader' not in locals():
            return await future_to_await

        # 3. Perform Generation
        start_time = time.perf_counter()
        logger.info("START AI Description Generation | title='%s' | dept='%s'", title_clean, department)

        try:
            result = await self._generate_description_from_llm(
                title_clean, department, employment_type, location, skills, experience
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.info("SUCCESS AI Description Generation | title='%s' | elapsed=%.1fms", title_clean, elapsed_ms)

            self._cache[cache_key] = CacheEntry(result, ttl_seconds=600.0)
            if not future_to_await.done():
                future_to_await.set_result(result)
            return result
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning("AI Description LLM Exception (using fallback) | err=%s | elapsed=%.1fms", exc, elapsed_ms)
            fallback = self._build_description_fallback(
                title_clean, department, employment_type, location, skills, experience
            )
            self._cache[cache_key] = CacheEntry(fallback, ttl_seconds=300.0)
            if not future_to_await.done():
                future_to_await.set_result(fallback)
            return fallback
        finally:
            async with self._lock:
                self._in_flight.pop(cache_key, None)

    async def _generate_autofill_from_llm(
        self,
        title: str,
        experience: Optional[str],
        salary_min: Optional[float],
        salary_max: Optional[float],
        currency: Optional[str],
    ) -> Dict[str, Any]:
        is_healthy = await ollama_client.check_health()
        if not is_healthy:
            return self._build_autofill_fallback(title, experience, salary_min, salary_max, currency)

        prompt = f"""You are an expert HR copywriter and recruiter.
Generate a complete job posting template for:
- Role Title: {title}
- Experience Level: {experience or 'Not specified'}
- Salary Min: {salary_min or 'Not specified'}
- Salary Max: {salary_max or 'Not specified'}
- Currency: {currency or 'USD'}

Infer realistic defaults for all missing values:
- department: E.g., 'Engineering', 'Marketing', 'Product Management', 'Design', 'Sales', 'HR', etc.
- employment_type: Must be exactly one of: 'Full-time', 'Part-time', 'Contract', 'Internship'.
- location: E.g., 'Remote', 'San Francisco, CA', 'Bengaluru, India', 'London, UK', etc.
- work_mode: Must be exactly one of: 'Remote', 'Hybrid', 'Onsite'.
- vacancies: Integer default, e.g. 1.
- skills: Array of 4-6 key skill strings.
- description: 2-3 sentence overview of the role.
- responsibilities: Array of 4-6 core duties.
- requirements: Array of 4-6 required qualifications.
- benefits: Array of 4-5 employee benefits.

Return ONLY strict valid JSON matching the requested keys."""

        sys_prompt = "You are a professional HR assistant. Output strictly valid raw JSON with no extra text or markdown formatting."

        resp_text = await ollama_client.generate_completion(
            prompt=prompt,
            system_prompt=sys_prompt,
            json_format=True,
            options={"temperature": 0.4, "num_predict": 768},
        )

        if not resp_text:
            return self._build_autofill_fallback(title, experience, salary_min, salary_max, currency)

        parsed = self._clean_and_parse_json(resp_text)
        if not parsed or not isinstance(parsed, dict):
            return self._build_autofill_fallback(title, experience, salary_min, salary_max, currency)

        return {
            "department": parsed.get("department") or self._infer_department(title),
            "employment_type": parsed.get("employment_type") or "Full-time",
            "location": parsed.get("location") or "Remote",
            "work_mode": parsed.get("work_mode") or "Remote",
            "vacancies": int(parsed.get("vacancies") or 1),
            "skills": parsed.get("skills") or self._infer_skills(title),
            "description": parsed.get("description") or f"We are seeking a talented {title} to join our growing team.",
            "responsibilities": parsed.get("responsibilities") or [
                f"Lead execution of key {title} initiatives and deliverables",
                "Collaborate with cross-functional team members to drive technical and business goals",
                "Maintain high standards of quality, reliability, and documentation",
            ],
            "requirements": parsed.get("requirements") or [
                f"Proven experience in a {title} or related domain role",
                "Strong analytical, technical, and communication skills",
                "Ability to thrive in a fast-paced, collaborative team environment",
            ],
            "benefits": parsed.get("benefits") or [
                "Competitive base salary and performance incentives",
                "Flexible remote or hybrid work environment",
                "Comprehensive health, medical, and wellness coverage",
                "Generous paid time off and professional growth allowance",
            ],
        }

    async def _generate_description_from_llm(
        self,
        title: str,
        department: Optional[str],
        employment_type: Optional[str],
        location: Optional[str],
        skills: Optional[List[str]],
        experience: Optional[str],
    ) -> str:
        is_healthy = await ollama_client.check_health()
        if not is_healthy:
            return self._build_description_fallback(title, department, employment_type, location, skills, experience)

        skills_str = ", ".join(skills) if skills else "relevant domain skills"
        prompt = f"""Write a comprehensive and attractive job description for:
Position: {title}
Department: {department or 'Engineering'}
Employment Type: {employment_type or 'Full-time'}
Location: {location or 'Remote'}
Required Skills: {skills_str}
Experience: {experience or '3+ years'}

Format as structured Markdown with these exact sections:
# {title}

## Role Summary
A compelling 2-3 sentence summary of why this role exists and its impact.

## Key Responsibilities
- 4-6 specific responsibility bullet points

## Requirements & Qualifications
- 4-6 technical & professional requirement bullet points

## Preferred Skills
- 3-4 nice-to-have skill bullet points

## Compensation & Benefits
- Competitive salary, healthcare, remote work perks, learning budget

## Equal Opportunity Employer
Our company is an Equal Opportunity Employer. We celebrate diversity and are committed to creating an inclusive, respectful environment for all employees."""

        sys_prompt = "You are an expert HR copywriter. Return ONLY clean, professional markdown content."

        resp_text = await ollama_client.generate_completion(
            prompt=prompt,
            system_prompt=sys_prompt,
            options={"temperature": 0.5, "num_predict": 1024},
        )

        if not resp_text or len(resp_text.strip()) < 50:
            return self._build_description_fallback(title, department, employment_type, location, skills, experience)

        return resp_text.strip()

    def _clean_and_parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]

        try:
            return json.loads(text)
        except Exception:
            return None

    def _infer_department(self, title: str) -> str:
        t = title.lower()
        if any(w in t for w in ["engineer", "developer", "backend", "frontend", "fullstack", "software", "architect", "data", "qa"]):
            return "Engineering"
        if any(w in t for w in ["product", "pm"]):
            return "Product Management"
        if any(w in t for w in ["designer", "ui", "ux"]):
            return "Design"
        if any(w in t for w in ["marketing", "growth", "seo"]):
            return "Marketing"
        if any(w in t for w in ["sales", "account"]):
            return "Sales"
        if any(w in t for w in ["hr", "recruiter", "talent"]):
            return "Human Resources"
        return "General"

    def _infer_skills(self, title: str) -> List[str]:
        t = title.lower()
        if "backend" in t or "python" in t:
            return ["Python", "FastAPI", "PostgreSQL", "Docker", "REST APIs"]
        if "frontend" in t or "react" in t:
            return ["React", "TypeScript", "Tailwind CSS", "Next.js", "State Management"]
        if "fullstack" in t:
            return ["React", "Node.js", "TypeScript", "PostgreSQL", "Docker"]
        return ["Communication", "Problem Solving", "Teamwork", "Project Management", "Domain Expertise"]

    def _build_autofill_fallback(
        self,
        title: str,
        experience: Optional[str],
        salary_min: Optional[float],
        salary_max: Optional[float],
        currency: Optional[str],
    ) -> Dict[str, Any]:
        dept = self._infer_department(title)
        skills = self._infer_skills(title)
        return {
            "department": dept,
            "employment_type": "Full-time",
            "location": "Remote",
            "work_mode": "Remote",
            "vacancies": 1,
            "skills": skills,
            "description": f"We are actively seeking a motivated and experienced {title} to join our {dept} team.",
            "responsibilities": [
                f"Design, build, and deliver high-impact solutions for {title} workflows",
                "Collaborate closely with team leads and cross-functional partners",
                "Maintain code quality, documentation, and operational standards",
                "Identify opportunities for operational efficiency and technical optimization",
            ],
            "requirements": [
                f"Proven hands-on experience in a {title} role ({experience or '3+ years'})",
                f"Strong proficiency with {', '.join(skills[:3])}",
                "Excellent communication, teamwork, and problem-solving abilities",
                "Degree or equivalent practical experience in relevant domain",
            ],
            "benefits": [
                "Competitive compensation package with performance incentives",
                "Flexible remote / hybrid work environment",
                "Comprehensive medical, dental, and health coverage",
                "Generous paid time off and professional growth allowance",
            ],
        }

    def _build_description_fallback(
        self,
        title: str,
        department: Optional[str],
        employment_type: Optional[str],
        location: Optional[str],
        skills: Optional[List[str]],
        experience: Optional[str],
    ) -> str:
        dept = department or self._infer_department(title)
        emp_type = employment_type or "Full-time"
        loc = location or "Remote"
        skills_str = ", ".join(skills) if skills else ", ".join(self._infer_skills(title))
        exp_str = experience or "3+ years"

        return f"""# {title}

## Role Summary
We are seeking a talented and driven **{title}** to join our **{dept}** department. In this role, you will be responsible for executing key deliverables, building high-quality solutions, and driving impact across the team.

## Key Responsibilities
- Drive execution and delivery of key initiatives for the **{title}** position.
- Collaborate with engineering, product, and leadership teams to ensure seamless cross-functional execution.
- Maintain high standards of quality, system reliability, and technical documentation.
- Continuously optimize workflows, processes, and core performance metrics.

## Requirements & Qualifications
- **{exp_str}** of hands-on experience in a **{title}** or closely related domain role.
- Demonstrated technical proficiency with: **{skills_str}**.
- Proven ability to solve complex problems and communicate effectively within a team environment.
- Bachelor's degree or equivalent practical experience in a relevant field.

## Preferred Skills
- Experience working in fast-paced agile environments.
- Familiarity with modern cloud tooling, automated testing, and CI/CD workflows.

## Compensation & Benefits
- **Employment Type**: {emp_type}
- **Location**: {loc}
- **Compensation**: Highly competitive base salary with performance bonuses.
- **Perks**: Comprehensive health insurance, remote work allowance, flexible PTO, and continuous learning stipend.

## Equal Opportunity Employer
Our organization is an Equal Opportunity Employer. We celebrate diversity and are committed to creating an inclusive, respectful environment for all employees regardless of race, gender, background, or identity."""

"""Resume Cleaner Service for normalizing and deduplicating extracted candidate data."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Comprehensive skill synonym mapping
SKILL_SYNONYMS: dict[str, str] = {
    # JavaScript & TypeScript
    "js": "JavaScript",
    "javascript": "JavaScript",
    "java script": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "type script": "TypeScript",
    "node": "Node.js",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "node js": "Node.js",
    "react": "React",
    "reactjs": "React",
    "react.js": "React",
    "react js": "React",
    "react native": "React Native",
    "react-native": "React Native",
    "next": "Next.js",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "next js": "Next.js",
    "vue": "Vue.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "vue js": "Vue.js",
    "nuxt": "Nuxt.js",
    "nuxtjs": "Nuxt.js",
    "nuxt.js": "Nuxt.js",
    "angular": "Angular",
    "angularjs": "Angular",
    "angular.js": "Angular",
    "express": "Express.js",
    "expressjs": "Express.js",
    "express.js": "Express.js",
    "redux": "Redux",
    "redux toolkit": "Redux",
    "rtk": "Redux",

    # Python Ecosystem
    "py": "Python",
    "python": "Python",
    "python3": "Python",
    "python 3": "Python",
    "fastapi": "FastAPI",
    "fast api": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "scipy": "SciPy",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "keras": "Keras",
    "celery": "Celery",
    "pydantic": "Pydantic",
    "sqlalchemy": "SQLAlchemy",

    # Databases & Caches
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "psql": "PostgreSQL",
    "postgre sql": "PostgreSQL",
    "mongo": "MongoDB",
    "mongodb": "MongoDB",
    "mongo db": "MongoDB",
    "mysql": "MySQL",
    "my sql": "MySQL",
    "sql server": "MS SQL Server",
    "mssql": "MS SQL Server",
    "sqlite": "SQLite",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "elastic search": "Elasticsearch",
    "dynamodb": "DynamoDB",
    "cassandra": "Cassandra",
    "sql": "SQL",
    "nosql": "NoSQL",

    # Cloud & DevOps
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "GCP",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "azure": "Azure",
    "microsoft azure": "Azure",
    "ms azure": "Azure",
    "docker": "Docker",
    "containers": "Docker",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "kube": "Kubernetes",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "jenkins": "Jenkins",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "ci cd": "CI/CD",
    "git": "Git",
    "github": "Git",
    "gitlab": "Git",
    "linux": "Linux",
    "unix": "Linux",
    "bash": "Bash",
    "shell": "Shell",

    # Web & Architecture
    "html": "HTML5",
    "html5": "HTML5",
    "css": "CSS3",
    "css3": "CSS3",
    "tailwind": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    "tailwind css": "Tailwind CSS",
    "bootstrap": "Bootstrap",
    "sass": "Sass",
    "scss": "Sass",
    "graphql": "GraphQL",
    "graph ql": "GraphQL",
    "rest": "REST API",
    "restful": "REST API",
    "rest api": "REST API",
    "restful api": "REST API",
    "microservices": "Microservices",
    "grpc": "gRPC",
    "websockets": "WebSockets",
    "kafka": "Kafka",
    "rabbitmq": "RabbitMQ",

    # Languages
    "c++": "C++",
    "cpp": "C++",
    "c#": "C#",
    "csharp": "C#",
    "c sharp": "C#",
    "golang": "Go",
    "go": "Go",
    "rust": "Rust",
    "java": "Java",
    "kotlin": "Kotlin",
    "swift": "Swift",
    "ruby": "Ruby",
    "php": "PHP",
    "scala": "Scala",

    # AI & Data Science
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "dl": "Deep Learning",
    "deep learning": "Deep Learning",
    "nlp": "Natural Language Processing",
    "natural language processing": "Natural Language Processing",
    "cv": "Computer Vision",
    "computer vision": "Computer Vision",
    "llm": "LLM",
    "large language models": "LLM",
    "genai": "Generative AI",
    "generative ai": "Generative AI",
}

SOFT_SKILLS_SET = {
    "communication", "teamwork", "leadership", "problem solving",
    "critical thinking", "time management", "adaptability", "collaboration",
    "creativity", "work ethic", "conflict resolution", "decision making",
    "interpersonal skills", "negotiation", "emotional intelligence",
    "agile", "scrum", "mentoring", "presentation", "public speaking",
}


class ResumeCleanerService:
    """Service to clean, normalize, and deduplicate extracted resume fields."""

    def clean_email(self, email: str | None) -> str | None:
        """Clean and validate email address."""
        if not email:
            return None
        cleaned = email.strip().lower()
        match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", cleaned)
        return match.group(0) if match else None

    def clean_phone(self, phone: str | None) -> str | None:
        """Clean phone number format while preserving international prefix."""
        if not phone:
            return None
        cleaned = re.sub(r"[^\d+]", "", phone.strip())
        if len(re.sub(r"[^\d]", "", cleaned)) < 7:
            return None
        return cleaned

    def clean_skills(self, skills: list[str]) -> tuple[list[str], list[str], list[str]]:
        """Normalize, deduplicate, and split skills into all_skills, technical_skills, and soft_skills."""
        if not skills:
            return [], [], []

        seen: set[str] = set()
        cleaned_skills: list[str] = []
        technical_skills: list[str] = []
        soft_skills: list[str] = []

        for skill in skills:
            if not skill or not isinstance(skill, str):
                continue
            normalized_key = skill.strip().lower()
            if not normalized_key or len(normalized_key) < 2:
                continue

            # Standardize using synonym map if available
            canonical_name = SKILL_SYNONYMS.get(normalized_key, skill.strip().title())

            if canonical_name.lower() not in seen:
                seen.add(canonical_name.lower())
                cleaned_skills.append(canonical_name)

                if canonical_name.lower() in SOFT_SKILLS_SET:
                    soft_skills.append(canonical_name)
                else:
                    technical_skills.append(canonical_name)

        return cleaned_skills, technical_skills, soft_skills

    def calculate_experience_from_dates(self, work_history: list[dict[str, Any]]) -> float | None:
        """Calculate total experience in years from work history start and end dates."""
        if not work_history:
            return None

        total_months = 0
        date_patterns = [
            r"([a-zA-Z]{3,9})\s+(\d{4})",       # Jan 2020
            r"(\d{1,2})/(\d{4})",               # 01/2020
            r"(\d{1,2})-(\d{4})",               # 01-2020
            r"(\d{4})",                         # 2020
        ]

        current_year = datetime.now().year
        current_month = datetime.now().month

        for job in work_history:
            if not isinstance(job, dict):
                continue

            # Check if duration_months is explicitly provided
            if job.get("duration_months") and isinstance(job["duration_months"], (int, float)):
                total_months += int(job["duration_months"])
                continue

            start_str = str(job.get("start_date") or "").strip()
            end_str = str(job.get("end_date") or "").strip().lower()
            is_current = job.get("is_current", False) or end_str in ("present", "current", "now", "ongoing")

            start_year, start_month = self._parse_date_components(start_str)
            if not start_year:
                continue

            if is_current:
                end_year, end_month = current_year, current_month
            else:
                end_year, end_month = self._parse_date_components(end_str)
                if not end_year:
                    end_year, end_month = start_year, 12

            if end_year >= start_year:
                months = (end_year - start_year) * 12 + (end_month - start_month)
                if months > 0:
                    total_months += months

        if total_months > 0:
            return round(total_months / 12.0, 1)

        return None

    @staticmethod
    def _parse_date_components(date_str: str) -> tuple[int | None, int]:
        """Helper to extract (year, month) from date string."""
        if not date_str:
            return None, 1

        month_map = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            "january": 1, "february": 2, "march": 3, "april": 4,
            "june": 6, "july": 7, "august": 8, "september": 9,
            "october": 10, "november": 11, "december": 12,
        }

        # Look for 4 digit year
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", date_str)
        if not year_match:
            return None, 1
        year = int(year_match.group(1))

        # Look for month name or numeric month
        month = 1
        for name, num in month_map.items():
            if name in date_str.lower():
                month = num
                break
        else:
            num_month_match = re.search(r"\b(0?[1-9]|1[0-2])[-/]", date_str)
            if num_month_match:
                month = int(num_month_match.group(1))

        return year, month

    def clean_experience_years(
        self,
        years: float | int | None,
        work_history: list[dict[str, Any]] | None = None,
        raw_text: str = ""
    ) -> float:
        """Sanitize total experience years, prioritizing date-calculated experience when reliable."""
        # 1. Try date-based calculation
        if work_history:
            date_exp = self.calculate_experience_from_dates(work_history)
            if date_exp is not None and date_exp > 0:
                return date_exp

        # 2. Use direct parsed years if valid
        if years is not None and isinstance(years, (int, float)) and years >= 0:
            return round(float(years), 1)

        # 3. Fallback regex search in raw text
        if raw_text:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years?|yrs?)", raw_text, re.IGNORECASE)
            if match:
                try:
                    return round(float(match.group(1)), 1)
                except ValueError:
                    pass

        return 0.0

    def clean_parsed_data(self, data: dict[str, Any], raw_text: str = "") -> dict[str, Any]:
        """Normalize complete parsed resume dictionary."""
        cleaned = dict(data)

        cleaned["email"] = self.clean_email(cleaned.get("email"))
        cleaned["phone"] = self.clean_phone(cleaned.get("phone"))

        raw_skills = cleaned.get("skills") or []
        if isinstance(raw_skills, dict):
            flat = []
            for sublist in raw_skills.values():
                if isinstance(sublist, list):
                    flat.extend(sublist)
            raw_skills = flat

        all_skills, tech_skills, soft_skills = self.clean_skills(raw_skills)

        cleaned["raw_skills"] = [s.strip() for s in raw_skills if isinstance(s, str) and s.strip()]
        cleaned["skills"] = all_skills
        cleaned["technical_skills"] = tech_skills or cleaned.get("technical_skills") or []
        cleaned["soft_skills"] = soft_skills or cleaned.get("soft_skills") or []

        work_hist = cleaned.get("work_history") or cleaned.get("experience") or []
        cleaned["total_experience_years"] = self.clean_experience_years(
            cleaned.get("total_experience_years"),
            work_history=work_hist if isinstance(work_hist, list) else None,
            raw_text=raw_text,
        )

        # Clean string lists (companies, languages, certifications, achievements)
        for key in ["previous_companies", "languages", "certifications", "achievements"]:
            items = cleaned.get(key) or []
            if isinstance(items, list):
                cleaned[key] = list(dict.fromkeys(item.strip() for item in items if isinstance(item, str) and item.strip()))

        return cleaned


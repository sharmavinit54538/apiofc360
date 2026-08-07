"""Production-Grade ATS Scoring Engine for dynamic JD-Resume match evaluation."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Configurable evaluation weights (Total = 1.0 / 100%)
DEFAULT_WEIGHTS = {
    "skills": 0.35,
    "experience": 0.20,
    "education": 0.10,
    "keywords": 0.15,
    "projects": 0.10,
    "certifications": 0.05,
    "resume_quality": 0.05,
}

# Technical Skill Synonyms & Aliases Normalization Map
SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "javascript": "javascript",
    "ts": "typescript",
    "typescript": "typescript",
    "py": "python",
    "python": "python",
    "node": "nodejs",
    "node.js": "nodejs",
    "nodejs": "nodejs",
    "react": "reactjs",
    "reactjs": "reactjs",
    "react.js": "reactjs",
    "vue": "vuejs",
    "vuejs": "vuejs",
    "angular": "angular",
    "angularjs": "angular",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "postgre": "postgresql",
    "fastapi": "fastapi",
    "fast api": "fastapi",
    "django": "django",
    "flask": "flask",
    "express": "expressjs",
    "expressjs": "expressjs",
    "k8s": "kubernetes",
    "kubernetes": "kubernetes",
    "aws": "amazon web services",
    "amazon web services": "amazon web services",
    "gcp": "google cloud",
    "google cloud": "google cloud",
    "google cloud platform": "google cloud",
    "azure": "microsoft azure",
    "microsoft azure": "microsoft azure",
    "mongo": "mongodb",
    "mongodb": "mongodb",
    "docker": "docker",
    "containers": "docker",
    "ml": "machine learning",
    "machine learning": "machine learning",
    "dl": "deep learning",
    "deep learning": "deep learning",
    "ai": "artificial intelligence",
    "artificial intelligence": "artificial intelligence",
    "nlp": "natural language processing",
    "natural language processing": "natural language processing",
    "sql": "sql",
    "structured query language": "sql",
    "nosql": "nosql",
    "cpp": "c++",
    "c++": "c++",
    "c#": "csharp",
    "csharp": "csharp",
    "golang": "go",
    "go": "go",
    "git": "git",
    "github": "git",
    "gitlab": "git",
    "ci/cd": "cicd",
    "cicd": "cicd",
    "rest": "rest api",
    "restful": "rest api",
    "rest api": "rest api",
    "graphql": "graphql",
    "microservices": "microservices",
    "redis": "redis",
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with", "by",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "but", "if", "not", "no", "can", "will", "would", "should", "our",
    "your", "my", "this", "that", "these", "those", "from", "as", "about", "into",
    "through", "during", "before", "after", "above", "below", "between", "under",
}


def normalize_skill_name(skill: str) -> str:
    """Normalize skill string to canonical lower-case form using synonym dictionary."""
    if not skill:
        return ""
    clean = skill.strip().lower()
    clean_sub = re.sub(r"[^\w\+\.#\-]", "", clean)
    return SKILL_ALIASES.get(clean, SKILL_ALIASES.get(clean_sub, clean))


class ATSScoringService:
    """Production ATS Scoring & Job Compatibility Engine."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = weights or DEFAULT_WEIGHTS

    def calculate_ats_score(
        self,
        candidate_data: dict[str, Any],
        job_data: dict[str, Any],
        formatting_score: float = 90.0,
    ) -> dict[str, Any]:
        """Calculate dynamic multi-dimensional ATS score and job compatibility."""
        # 1. Extract Candidate & Job Info
        job_title = (job_data.get("title") or "").strip()
        job_desc = (job_data.get("job_description") or "").strip()
        raw_job_skills = job_data.get("skills") or job_data.get("required_skills") or []
        min_experience = float(job_data.get("min_experience") or job_data.get("min_experience_years") or 0.0)

        # Extract skills from job description if explicitly empty
        if not raw_job_skills and job_desc:
            desc_words = [w.lower() for w in re.findall(r"\b[a-zA-Z\+\.#\-]{2,15}\b", job_desc)]
            raw_job_skills = [w for w in desc_words if normalize_skill_name(w) in SKILL_ALIASES]
            raw_job_skills = list(dict.fromkeys(raw_job_skills))[:10]

        raw_skills = candidate_data.get("skills") or []
        cand_skills = []
        if isinstance(raw_skills, dict):
            for k, v in raw_skills.items():
                if isinstance(v, list):
                    cand_skills.extend([x for x in v if isinstance(x, str)])
                elif isinstance(v, str):
                    cand_skills.append(v)
        elif isinstance(raw_skills, list):
            for item in raw_skills:
                if isinstance(item, str):
                    cand_skills.append(item)
                elif isinstance(item, dict):
                    for k, v in item.items():
                        if isinstance(v, list):
                            cand_skills.extend([x for x in v if isinstance(x, str)])
                        elif isinstance(v, str):
                            cand_skills.append(v)

        # Include technical_skills and soft_skills from candidate_data if they exist
        for alt_key in ["technical_skills", "soft_skills"]:
            alt_skills = candidate_data.get(alt_key)
            if isinstance(alt_skills, list):
                cand_skills.extend([x for x in alt_skills if isinstance(x, str)])

        cand_skills = list(dict.fromkeys(cand_skills))
        cand_exp = float(candidate_data.get("total_experience_years") or candidate_data.get("years_experience") or 0.0)
        cand_role = (candidate_data.get("current_designation") or candidate_data.get("current_role") or "").strip()
        cand_summary = (candidate_data.get("summary") or "").strip()
        cand_edu = candidate_data.get("education") or []
        cand_projects = candidate_data.get("projects") or []
        cand_certs = candidate_data.get("certifications") or []

        # 2. Skill Matching with Synonym Expansion
        matched_skills_map: dict[str, str] = {}
        missing_skills: list[str] = []
        extra_skills: list[str] = []

        norm_cand_skills = {normalize_skill_name(s): s for s in cand_skills}

        if raw_job_skills:
            for js in raw_job_skills:
                norm_js = normalize_skill_name(js)
                if norm_js in norm_cand_skills:
                    matched_skills_map[norm_js] = js.title()
                else:
                    # Partial / Substring check
                    match_found = False
                    for c_norm, c_orig in norm_cand_skills.items():
                        if norm_js in c_norm or c_norm in norm_js:
                            matched_skills_map[norm_js] = js.title()
                            match_found = True
                            break
                    if not match_found:
                        missing_skills.append(js.title())

            for cs in cand_skills:
                norm_cs = normalize_skill_name(cs)
                if norm_cs not in matched_skills_map:
                    extra_skills.append(cs.title())

            matched_skills = list(matched_skills_map.values())
            skill_score = (len(matched_skills) / len(raw_job_skills)) * 100.0
        else:
            matched_skills = [s.title() for s in cand_skills[:5]]
            skill_score = 65.0 if cand_skills else 30.0

        skill_score = min(100.0, max(0.0, skill_score))

        # 3. Experience Match Score
        if min_experience > 0:
            if cand_exp >= min_experience:
                experience_score = 100.0
            elif cand_exp > 0:
                experience_score = (cand_exp / min_experience) * 100.0
            else:
                experience_score = 35.0  # Graded fresher score
        else:
            experience_score = 100.0 if cand_exp >= 1.0 else 85.0

        experience_score = min(100.0, max(0.0, experience_score))

        # 4. Education Match Score
        if cand_edu:
            education_score = 95.0
        elif candidate_data.get("highest_qualification"):
            education_score = 85.0
        else:
            education_score = 50.0

        # 5. NLP Keyword Match Score (Jaccard Similarity over non-stopwords)
        cand_text = " ".join([
            cand_role,
            cand_summary,
            " ".join(cand_skills),
            candidate_data.get("raw_text") or "",
        ]).lower()
        job_text = " ".join([job_title, job_desc, " ".join(raw_job_skills)]).lower()

        cand_tokens = {w for w in re.findall(r"\b[a-z]{3,15}\b", cand_text) if w not in STOPWORDS}
        job_tokens = {w for w in re.findall(r"\b[a-z]{3,15}\b", job_text) if w not in STOPWORDS}

        if job_tokens and cand_tokens:
            intersection = cand_tokens.intersection(job_tokens)
            union = cand_tokens.union(job_tokens)
            jaccard = len(intersection) / len(union) if union else 0.0
            keyword_score = min(100.0, max(20.0, jaccard * 250.0))
        else:
            keyword_score = 50.0

        # 6. Projects & Portfolio Score
        if cand_projects:
            projects_score = min(100.0, 60.0 + len(cand_projects) * 15.0)
        else:
            projects_score = 40.0 if (cand_skills or cand_exp > 0) else 20.0

        # 7. Certifications Score
        if cand_certs:
            certifications_score = min(100.0, 70.0 + len(cand_certs) * 15.0)
        else:
            certifications_score = 30.0

        # 8. Resume Completeness & Quality
        completeness_checks = [
            bool(candidate_data.get("email")),
            bool(candidate_data.get("phone")),
            bool(cand_skills),
            bool(cand_edu or candidate_data.get("highest_qualification")),
            bool(cand_exp is not None),
        ]
        completeness_score = (sum(completeness_checks) / len(completeness_checks)) * 100.0
        resume_quality_score = (completeness_score * 0.6) + (formatting_score * 0.4)

        # 9. Compute Overall Weighted ATS Score
        w = self.weights
        overall_ats_score = (
            (skill_score * w.get("skills", 0.35)) +
            (experience_score * w.get("experience", 0.20)) +
            (education_score * w.get("education", 0.10)) +
            (keyword_score * w.get("keywords", 0.15)) +
            (projects_score * w.get("projects", 0.10)) +
            (certifications_score * w.get("certifications", 0.05)) +
            (resume_quality_score * w.get("resume_quality", 0.05))
        )
        overall_ats_score = min(100.0, max(0.0, round(overall_ats_score, 1)))

        # 10. Separate Job Match Score
        role_comp = 100.0 if (job_title and job_title.lower() in cand_role.lower()) else 60.0
        job_match_score = round((skill_score * 0.50) + (experience_score * 0.30) + (role_comp * 0.20), 1)
        job_match_score = min(100.0, max(0.0, job_match_score))

        # 11. Generate Actionable Recommendations
        recommendations: list[str] = []
        for ms in missing_skills[:5]:
            recommendations.append(f"Add required skill: {ms}")

        if min_experience > 0 and cand_exp < min_experience:
            diff = round(min_experience - cand_exp, 1)
            recommendations.append(f"Need {diff} more year(s) of experience to match job requirement.")

        if not cand_certs:
            recommendations.append("Consider adding relevant industry certifications.")

        if not cand_projects:
            recommendations.append("Include technical projects or portfolio links.")

        if keyword_score < 50.0:
            recommendations.append("Improve resume keyword alignment with job description.")

        return {
            "overall_ats_score": overall_ats_score,
            "job_match": job_match_score,
            "skill_match_score": round(skill_score, 1),
            "experience_match_score": round(experience_score, 1),
            "education_match_score": round(education_score, 1),
            "keyword_match_score": round(keyword_score, 1),
            "projects_score": round(projects_score, 1),
            "certifications_score": round(certifications_score, 1),
            "resume_quality_score": round(resume_quality_score, 1),
            "score_breakdown": {
                "skills": round(skill_score * w.get("skills", 0.35), 1),
                "experience": round(experience_score * w.get("experience", 0.20), 1),
                "education": round(education_score * w.get("education", 0.10), 1),
                "keywords": round(keyword_score * w.get("keywords", 0.15), 1),
                "projects": round(projects_score * w.get("projects", 0.10), 1),
                "certifications": round(certifications_score * w.get("certifications", 0.05), 1),
                "resume_quality": round(resume_quality_score * w.get("resume_quality", 0.05), 1),
            },
            "matched_skills": list(dict.fromkeys(matched_skills)),
            "missing_skills": list(dict.fromkeys(missing_skills)),
            "extra_skills": list(dict.fromkeys(extra_skills)),
            "recommendations": recommendations,
        }

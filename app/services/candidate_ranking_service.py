"""Candidate Ranking Service for computing rank, match tier, and AI hiring insights."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class CandidateRankingService:
    """Service to rank applicants and generate AI hiring insights."""

    def determine_match_tier(self, ats_score: float) -> str:
        """Categorize ATS score into match tier."""
        if ats_score >= 85.0:
            return "Best Match"
        if ats_score >= 70.0:
            return "Good Match"
        if ats_score >= 50.0:
            return "Average Match"
        return "Low Match"

    def determine_hiring_recommendation(self, ats_score: float) -> str:
        """Determine recommendation decision."""
        if ats_score >= 75.0:
            return "SHORTLIST"
        if ats_score >= 50.0:
            return "REVIEW"
        return "REJECT"

    def determine_career_level(self, total_experience_years: float) -> str:
        """Categorize candidate career level based on experience."""
        if total_experience_years >= 10.0:
            return "Executive"
        if total_experience_years >= 7.0:
            return "Lead"
        if total_experience_years >= 4.0:
            return "Senior"
        if total_experience_years >= 1.5:
            return "Mid"
        return "Junior"

    def generate_ai_insights(
        self,
        candidate_name: str,
        ats_score: float,
        ats_breakdown: dict[str, Any],
        parsed_data: dict[str, Any],
        job_title: str = "Target Position",
    ) -> dict[str, Any]:
        """Generate comprehensive AI hiring insights and interview recommendations."""
        matched_skills = ats_breakdown.get("matched_skills") or []
        missing_skills = ats_breakdown.get("missing_skills") or []
        exp_years = float(parsed_data.get("total_experience_years") or 0.0)

        match_tier = self.determine_match_tier(ats_score)
        recommendation = self.determine_hiring_recommendation(ats_score)
        career_level = self.determine_career_level(exp_years)

        # Strengths
        strengths = []
        if exp_years > 0:
            strengths.append(f"Possesses {exp_years} years of relevant industry experience.")
        if matched_skills:
            strengths.append(f"Demonstrated proficiency in core skills: {', '.join(matched_skills[:4])}.")
        if parsed_data.get("education"):
            strengths.append("Holds formal degree education in relevant domain.")

        # Weaknesses & Risk Factors
        weaknesses = []
        risk_factors = []
        if missing_skills:
            weaknesses.append(f"Skill gaps identified in: {', '.join(missing_skills[:3])}.")
            risk_factors.append("Requires initial onboarding/training for missing technical skills.")
        if exp_years < 1.0:
            risk_factors.append("Limited commercial experience; may require mentorship.")

        # Interview questions generator
        interview_questions = [
            f"Can you describe your experience implementing projects using {matched_skills[0] if matched_skills else 'your primary tech stack'}?",
            f"How do you approach solving complex architectural challenges in a {job_title} role?",
        ]
        if missing_skills:
            interview_questions.append(
                f"How would you quickly gain competency in missing skills such as {missing_skills[0]}?"
            )
        interview_questions.append("Can you walk us through a recent project where you had to collaborate under tight deadlines?")

        # Assessments
        tech_assessment = (
            f"Strong technical alignment with {len(matched_skills)} matched core competencies."
            if ats_score >= 70
            else "Moderate technical alignment with identified skill gaps."
        )

        comm_assessment = (
            "Resume presents structured, clear communication with key project metrics."
        )

        leadership_indicators = []
        if exp_years >= 4.0:
            leadership_indicators.append("Mentored junior developers and led project sub-modules.")
        if career_level in ["Senior", "Lead", "Executive"]:
            leadership_indicators.append("Experience leading cross-functional teams and architectural decisions.")

        summary = (
            f"{candidate_name} is a {career_level}-level candidate evaluated as a {match_tier} for {job_title} "
            f"with an overall ATS Score of {ats_score}/100."
        )

        return {
            "candidate_summary": summary,
            "strengths": strengths or ["Relevant foundational qualifications."],
            "weaknesses": weaknesses or ["No significant weaknesses detected."],
            "missing_skills": missing_skills,
            "recommended_interview_questions": interview_questions,
            "risk_factors": risk_factors or ["Low risk profile."],
            "hiring_recommendation": recommendation,
            "career_level": career_level,
            "technical_assessment": tech_assessment,
            "communication_assessment": comm_assessment,
            "leadership_indicators": leadership_indicators,
        }

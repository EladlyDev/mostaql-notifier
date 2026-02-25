"""Mostaql Notifier — AI Analysis Prompts.

Prompt-building functions for the AI job analysis pipeline. Produces
structured prompts that instruct the AI to return JSON with 6 scored
dimensions plus qualitative analysis fields.
"""

from __future__ import annotations

from typing import Any


def build_analysis_prompt(job_data: dict[str, Any], profile: dict[str, Any]) -> str:
    """Build the main job analysis prompt.

    Constructs a detailed prompt that presents the job data and
    freelancer profile, then requests a structured JSON analysis
    across 6 dimensions with qualitative fields.

    Args:
        job_data: Dict with all available job fields.
        profile: Dict with freelancer profile fields.

    Returns:
        Complete prompt string ready to send to the AI.
    """
    # ── Format job data ──────────────────────────────────
    title = job_data.get("title", "N/A")
    description = job_data.get("full_description", "") or job_data.get("brief_description", "")
    # Truncate description to save tokens
    if len(description) > 600:
        description = description[:600] + "..."

    category = job_data.get("category", "N/A")
    budget_raw = job_data.get("budget_raw", "N/A")
    budget_min = job_data.get("budget_min")
    budget_max = job_data.get("budget_max")
    duration = job_data.get("duration", "N/A")
    skills = job_data.get("skills", [])
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    proposals = job_data.get("proposals_count", 0)
    status = job_data.get("status", "N/A")
    time_posted = job_data.get("time_posted", "N/A")

    # Publisher info
    pub_name = job_data.get("publisher_name", "N/A")
    hire_rate = job_data.get("hire_rate", 0)
    hire_rate_raw = job_data.get("hire_rate_raw", "N/A")
    reg_date = job_data.get("registration_date", "N/A")
    open_proj = job_data.get("open_projects", 0)
    verified = job_data.get("identity_verified", False)

    # ── Format profile ───────────────────────────────────
    expert = ", ".join(profile.get("expert_skills", []))
    intermediate = ", ".join(profile.get("intermediate_skills", []))
    exp_years = profile.get("experience_years", 0)
    pref_budget = profile.get("preferred_budget_range", "N/A")

    budget_display = budget_raw
    if budget_min is not None and budget_max is not None:
        budget_display = f"{budget_raw} (${budget_min:.0f}-${budget_max:.0f})"

    skills_display = ", ".join(skills) if skills else "Not specified"

    return f"""You are a freelancing market analyst. Analyze this job for a specific freelancer.

=== JOB DATA ===
Title: {title}
Category: {category}
Budget: {budget_display}
Duration: {duration}
Status: {status}
Posted: {time_posted}
Proposals: {proposals}
Skills Required: {skills_display}
Description: {description}

=== PUBLISHER INFO ===
Name: {pub_name}
Hire Rate: {hire_rate_raw} ({hire_rate:.0f}%)
Registered: {reg_date}
Open Projects: {open_proj}
Identity Verified: {"Yes" if verified else "No"}

=== FREELANCER PROFILE ===
Expert Skills: {expert}
Intermediate Skills: {intermediate}
Experience: {exp_years} years
Preferred Budget: {pref_budget}

=== ANALYSIS INSTRUCTIONS ===
Score each dimension 0-100. Be CONSERVATIVE — underestimate rather than overestimate.

Score calibration:
- 0-20: Very negative signal
- 21-40: Below average, concerning
- 41-60: Average, uncertain, insufficient data
- 61-80: Above average, positive signal
- 81-100: Very strong positive signal (rare, needs strong evidence)

1. hiring_probability: Will the client actually hire someone?
   High (70+): verified identity, high hire rate (>60%), clear budget, past history
   Low (<40): new account, no hire history, vague budget, no verification

2. fit_score: Does this match the freelancer's skills?
   High (70+): multiple expert skills overlap, matching category, right experience level
   Low (<40): no skill overlap, wrong category, overqualified or underqualified

3. budget_fairness: Is the budget fair for the described work?
   High (70+): budget matches scope, competitive with market rates
   Low (<40): severely underpaid, unrealistic expectations for the budget

4. job_clarity: How well-defined is the job?
   High (70+): detailed description, clear deliverables, specific timeline
   Low (<40): vague description, unclear scope, no deliverables mentioned

5. competition_level: How favorable is the competition? (100 = almost no competition)
   High (70+): few proposals (<3), niche skills, recently posted
   Low (<40): many proposals (>10), generic skills, posted long ago

6. urgency_score: How time-sensitive is this job?
   High (70+): mentions deadline, urgent language, posted very recently
   Low (<40): no timeline pressure, posted days ago

Also provide:
- overall_score: Weighted average (fit_score×0.3 + hiring_probability×0.25 + budget_fairness×0.15 + job_clarity×0.1 + competition_level×0.1 + urgency_score×0.1)
- job_summary: 2-3 sentence summary in Arabic
- required_skills_analysis: Which freelancer skills match and what's missing (Arabic)
- red_flags: List of concerns (Arabic strings)
- green_flags: List of positives (Arabic strings)
- recommended_proposal_angle: Specific advice for a winning proposal (Arabic)
- estimated_real_budget: What the client would actually pay (e.g. "$50-$100")
- recommendation: One of "instant_alert", "digest", or "skip"
  - "instant_alert": overall_score >= 70 AND fit_score >= 60
  - "digest": overall_score >= 45 AND overall_score < 70
  - "skip": overall_score < 45
- recommendation_reason: Why this recommendation (Arabic)

Return ONLY a valid JSON object with exactly these keys. No markdown, no explanation, no extra text."""


def build_batch_summary_prompt(jobs: list[dict[str, Any]]) -> str:
    """Build a prompt for daily trend analysis.

    Given scored jobs from today, asks the AI for market observations,
    trending skills, budget trends, and recommendations.

    Args:
        jobs: List of dicts with title, category, budget, skills, overall_score.

    Returns:
        Complete prompt string for daily summary analysis.
    """
    # Build compact job list
    job_lines = []
    for i, j in enumerate(jobs[:30], 1):  # Cap at 30 to save tokens
        title = j.get("title", "?")[:60]
        score = j.get("overall_score", 0)
        budget = j.get("budget_raw", "N/A")
        skills = j.get("skills", [])
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",") if s.strip()]
        skills_str = ", ".join(skills[:4]) if skills else "N/A"
        job_lines.append(f"{i}. [{score}] {title} | {budget} | {skills_str}")

    jobs_text = "\n".join(job_lines)
    total = len(jobs)

    return f"""You are a freelancing market analyst. Analyze today's job market.

=== TODAY'S JOBS ({total} total, showing top {len(job_lines)}) ===
Format: [overall_score] Title | Budget | Skills
{jobs_text}

=== ANALYSIS REQUEST ===
Provide a daily market summary with these exact JSON keys:

- trending_skills: List of top 5 most in-demand skills today (Arabic)
- avg_budget_range: Average budget range observed (e.g. "$25-$100")
- market_observations: 3-5 bullet points about today's market (Arabic strings)
- recommendations: 2-3 actionable tips for the freelancer (Arabic strings)
- best_opportunities_count: How many jobs scored 60+ today (integer)
- market_health: "active", "moderate", or "slow"

Return ONLY valid JSON. No markdown, no explanation."""

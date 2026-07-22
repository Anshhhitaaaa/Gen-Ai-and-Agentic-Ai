import re
import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.project import Project
from app.models.report import Report

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def parse_github_url(url: str):
    """Extracts owner/repo from a GitHub URL like https://github.com/owner/repo"""
    match = re.search(r"github\.com/([^/]+)/([^/]+?)(\.git)?/?$", url)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def fetch_github_data(owner: str, repo: str):
    headers = {"Accept": "application/vnd.github+json"}
    base = f"https://api.github.com/repos/{owner}/{repo}"

    result = {"languages": {}, "open_issues": None, "recent_commits": []}

    try:
        lang_res = requests.get(f"{base}/languages", headers=headers, timeout=10)
        if lang_res.status_code == 200:
            result["languages"] = lang_res.json()

        repo_res = requests.get(base, headers=headers, timeout=10)
        if repo_res.status_code == 200:
            result["open_issues"] = repo_res.json().get("open_issues_count")

        commits_res = requests.get(f"{base}/commits", headers=headers, params={"per_page": 30}, timeout=10)
        if commits_res.status_code == 200:
            result["recent_commits"] = [
                c["commit"]["author"]["date"] for c in commits_res.json() if c.get("commit")
            ]
    except requests.RequestException:
        pass  # return whatever we got; frontend handles partial data

    return result


@router.get("/{project_id}")
def get_analytics(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Health score trend + latest category scores, from existing reports
    reports = (
        db.query(Report)
        .filter(Report.project_id == project_id)
        .order_by(Report.generated_at)
        .all()
    )

    health_score_trend = []
    category_scores = []

    for r in reports:
        scores = [
            r.architecture_score, r.scalability_score, r.documentation_score,
            r.deployment_readiness_score, r.code_quality_score,
            r.security_score, r.performance_score,
        ]
        valid_scores = [s for s in scores if s is not None]
        if valid_scores:
            avg = sum(valid_scores) / len(valid_scores)
            health_score_trend.append({
                "date": r.generated_at.isoformat(),
                "score": round(avg, 1),
            })

    if reports:
        latest = reports[-1]
        field_labels = [
            ("Architecture", latest.architecture_score),
            ("Scalability", latest.scalability_score),
            ("Documentation", latest.documentation_score),
            ("Deployment Readiness", latest.deployment_readiness_score),
            ("Code Quality", latest.code_quality_score),
            ("Security", latest.security_score),
            ("Performance", latest.performance_score),
        ]
        category_scores = [
            {"category": name, "score": score}
            for name, score in field_labels if score is not None
        ]

    # GitHub data, only if this project has a github_url
    tech_stack_breakdown = []
    commit_activity = []
    open_issues = None

    if project.github_url:
        owner, repo = parse_github_url(project.github_url)
        if owner and repo:
            gh_data = fetch_github_data(owner, repo)

            total_bytes = sum(gh_data["languages"].values())
            if total_bytes > 0:
                tech_stack_breakdown = [
                    {"name": lang, "value": round((bytes_ / total_bytes) * 100, 1)}
                    for lang, bytes_ in gh_data["languages"].items()
                ]

            open_issues = gh_data["open_issues"]

            # Group commits by week for a simple activity chart
            from collections import Counter
            from datetime import datetime
            week_counts = Counter()
            for date_str in gh_data["recent_commits"]:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                week_label = dt.strftime("%b %d")
                week_counts[week_label] += 1
            commit_activity = [{"week": k, "commits": v} for k, v in week_counts.items()]

    return {
        "health_score_trend": health_score_trend,
        "category_scores": category_scores,
        "tech_stack_breakdown": tech_stack_breakdown,
        "commit_activity": commit_activity,
        "open_issues": open_issues,
        "has_github_data": bool(project.github_url),
    }
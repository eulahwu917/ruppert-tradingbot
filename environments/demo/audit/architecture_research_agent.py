"""
Architecture Research Agent — weekly quant research scanner.

Runs every Sunday 9am via Task Scheduler.
Fetches recent quant/trading repos and papers, compares to current Ruppert
architecture via Claude Opus, writes gap analysis to Obsidian vault,
sends summary to David via Telegram.

Usage: python architecture_research_agent.py
"""

import json
import logging
import os
import sys
import requests
from datetime import date, datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
OBSIDIAN_DIR = Path(r"C:\Users\David Wu\Obsidian Vault\5_AI Knowledge\Ruppert-Agent")
SECRETS_DIR  = Path(__file__).parent.parent / "secrets"

# ── Current Ruppert Architecture Summary (injected into Opus prompt) ──────────
ARCHITECTURE_SUMMARY = """
Ruppert is a Kalshi prediction market trading bot focused on crypto trading:
- Crypto: BTC/ETH/XRP/SOL/DOGE price bands, Kraken prices, band probability model, smart money wallet tracker
  - Modules: crypto_dir_15m (directional 15-min), crypto_band_daily (price bands), crypto_threshold_daily (threshold)

Architecture principles:
- LLMs generate signals, deterministic math executes (strategy.py)
- Confidence-tiered Kelly sizing (6 tiers: 25-80%+, 5-16% Kelly)
- Monolithic cycle (ruppert_cycle.py), per-domain module functions
- Brier score tracking for calibration validation
- Autoresearch loop (git-branching, Bonferroni correction, per-domain 30-trade threshold)
- Single source of truth for capital (capital.py)
- Data health checks daily at 6:45am

Current gaps being watched:
- Brier score calibration not yet validated (accumulating data)
- Per-domain autoresearch threshold not yet reached
"""


def fetch_github_trending(topics: list, max_per_topic: int = 3) -> list:
    """Fetch trending GitHub repos for given topics via GitHub Search API."""
    repos = []
    headers = {"Accept": "application/vnd.github+json"}
    for topic in topics:
        try:
            r = requests.get(
                "https://api.github.com/search/repositories",
                params={
                    "q": f"topic:{topic} stars:>50",
                    "sort": "updated",
                    "order": "desc",
                    "per_page": max_per_topic,
                },
                headers=headers,
                timeout=10,
            )
            if r.status_code == 200:
                for repo in r.json().get("items", []):
                    repos.append({
                        "name": repo["full_name"],
                        "description": repo.get("description", ""),
                        "stars": repo["stargazers_count"],
                        "url": repo["html_url"],
                        "updated": repo["updated_at"][:10],
                        "topic": topic,
                    })
        except Exception as e:
            logger.warning(f"GitHub fetch failed for topic {topic}: {e}")
    return repos


def fetch_arxiv_papers(max_results: int = 5) -> list:
    """Fetch recent q-fin papers from arXiv."""
    papers = []
    try:
        r = requests.get(
            "http://export.arxiv.org/api/query",
            params={
                "search_query": "cat:q-fin.TR OR cat:q-fin.PM",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": max_results,
            },
            timeout=15,
        )
        if r.status_code == 200:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.text)
            ns = "{http://www.w3.org/2005/Atom}"
            for entry in root.findall(f"{ns}entry"):
                papers.append({
                    "title":   entry.findtext(f"{ns}title", "").strip(),
                    "summary": entry.findtext(f"{ns}summary", "").strip()[:500],
                    "url":     entry.findtext(f"{ns}id", ""),
                    "date":    entry.findtext(f"{ns}published", "")[:10],
                })
    except Exception as e:
        logger.warning(f"arXiv fetch failed: {e}")
    return papers


def call_opus(repos: list, papers: list) -> str:
    """Call Claude Opus to analyze repos/papers vs current architecture."""
    try:
        import anthropic
        client = anthropic.Anthropic()

        sources_text = ""
        if repos:
            sources_text += "\n\n## GitHub Repos (recent/trending)\n"
            for r in repos:
                sources_text += f"- [{r['name']}]({r['url']}) ({r['stars']} stars, updated {r['updated']}): {r['description']}\n"
        if papers:
            sources_text += "\n\n## arXiv Papers (recent q-fin)\n"
            for p in papers:
                sources_text += f"- [{p['title']}]({p['url']}) ({p['date']}): {p['summary'][:200]}...\n"

        prompt = f"""You are the Architecture Research Agent for Ruppert, a Kalshi prediction market trading bot.

## Current Ruppert Architecture
{ARCHITECTURE_SUMMARY}

## This Week's Sources
{sources_text}

## Your Task
Compare this week's repos and papers against the current Ruppert architecture.
Produce a concise gap analysis in markdown format:

1. **Relevant Findings** — what's actually applicable to Kalshi prediction markets (be selective, most equity/HFT stuff is not relevant)
2. **Gaps Identified** — specific things we're missing or doing worse than state-of-art
3. **Recommendation** — 1-3 concrete actionable items, ranked by expected impact
4. **Pass** — things we're already doing correctly that were validated by this week's sources

Be direct. Skip anything not applicable to binary prediction markets. Max 600 words."""

        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f"Opus call failed: {e}")
        return f"ERROR: Opus call failed — {e}"


def write_obsidian(analysis: str, repos: list, papers: list) -> Path:
    """Write gap analysis to Obsidian vault."""
    today = date.today().isoformat()
    filename = f"{today} Architecture Research.md"
    output_path = OBSIDIAN_DIR / filename

    content = f"""# Architecture Research — {today}

**Agent:** Architecture Research Agent (Opus)
**Sources:** {len(repos)} GitHub repos, {len(papers)} arXiv papers

---

{analysis}

---

## Raw Sources

### GitHub Repos
"""
    for r in repos:
        content += f"- [{r['name']}]({r['url']}) ({r['stars']} \u2b50, topic: {r['topic']}): {r['description']}\n"

    content += "\n### arXiv Papers\n"
    for p in papers:
        content += f"- [{p['title']}]({p['url']}) ({p['date']})\n"

    try:
        OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        logger.info(f"Written to Obsidian: {output_path}")
    except Exception as e:
        logger.error(f"Obsidian write failed: {e}")

    return output_path


def send_telegram_summary(analysis: str, obsidian_path: Path):
    """Send brief summary to David via Telegram."""
    try:
        # Extract first 3 lines of analysis as summary
        lines = [l for l in analysis.strip().splitlines() if l.strip()]
        summary_lines = lines[:6]
        summary = "\n".join(summary_lines)

        msg = f"\U0001f4d0 Weekly Architecture Research\n\n{summary}\n\n_Full report in Obsidian: {obsidian_path.name}_"

        from agents.ruppert.data_scientist.logger import send_telegram
        send_telegram(msg)
        logger.info("Telegram summary sent")
    except Exception as e:
        logger.warning(f"Telegram send failed: {e}")


def main():
    logger.info("=== Architecture Research Agent starting ===")

    # Fetch sources
    topics = ["kalshi", "prediction-markets", "quantitative-trading", "algorithmic-trading", "market-making"]
    repos  = fetch_github_trending(topics, max_per_topic=2)
    papers = fetch_arxiv_papers(max_results=5)

    logger.info(f"Fetched {len(repos)} repos, {len(papers)} papers")

    if not repos and not papers:
        logger.warning("No sources fetched — skipping analysis")
        return

    # Call Opus
    analysis = call_opus(repos, papers)

    # Write to Obsidian
    obsidian_path = write_obsidian(analysis, repos, papers)

    # Send Telegram summary
    send_telegram_summary(analysis, obsidian_path)

    logger.info("=== Architecture Research Agent complete ===")


if __name__ == "__main__":
    main()

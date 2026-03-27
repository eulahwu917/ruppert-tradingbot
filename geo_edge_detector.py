"""
Geopolitical Edge Detector — Two-stage LLM pipeline for geo market analysis.

Stage 1: Haiku classifier (cheap ~$0.001/call)
  - Classifies relevance and severity of a GDELT event to a Kalshi market
  - Only passes severity >= 3 to Stage 2

Stage 2: Sonnet estimator (accurate ~$0.01/call)
  - Estimates probability a market resolves YES given a geopolitical event
  - Returns structured JSON with probability, confidence, and reasoning

Uses subprocess calls to `claude --print` CLI for LLM inference.
"""
import subprocess
import json
import sys
import os
from datetime import date
from logger import log_activity

# Log file for LLM screening results
GEO_EDGE_LOG = os.path.join(os.path.dirname(__file__), 'logs', 'geo_edge_detector.jsonl')


def _call_claude(prompt, model='haiku', timeout=30):
    """
    Call Claude CLI via subprocess. Returns parsed JSON or None on failure.

    Args:
        prompt: Text prompt to send
        model: 'haiku' or 'sonnet'
        timeout: Max seconds to wait
    """
    model_flag = {
        'haiku': 'haiku',
        'sonnet': 'sonnet',
    }.get(model, 'haiku')

    try:
        result = subprocess.run(
            ['claude', '--print', '--model', model_flag, prompt],
            capture_output=True, text=True, timeout=timeout,
            cwd=os.path.dirname(__file__) or '.',
        )
        if result.returncode != 0:
            log_activity(f"[GeoEdge] claude --print ({model}) failed: {result.stderr[:200]}")
            return None

        output = result.stdout.strip()

        # Try to extract JSON from the output
        # Claude may wrap JSON in markdown code blocks
        if '```json' in output:
            start = output.index('```json') + 7
            end = output.index('```', start)
            output = output[start:end].strip()
        elif '```' in output:
            start = output.index('```') + 3
            end = output.index('```', start)
            output = output[start:end].strip()

        return json.loads(output)

    except subprocess.TimeoutExpired:
        log_activity(f"[GeoEdge] claude --print ({model}) timed out after {timeout}s")
        return None
    except json.JSONDecodeError:
        log_activity(f"[GeoEdge] claude --print ({model}) returned non-JSON: {output[:200]}")
        return None
    except FileNotFoundError:
        log_activity("[GeoEdge] claude CLI not found — is Claude Code installed?")
        return None
    except Exception as e:
        log_activity(f"[GeoEdge] claude --print ({model}) error: {e}")
        return None


def stage1_classify(event, market_title):
    """
    Stage 1 — Haiku classifier.
    Classifies whether a GDELT event is relevant to a Kalshi market.

    Args:
        event: dict with keys: title, event_type, country, severity
        market_title: Kalshi market title string

    Returns:
        {relevant: bool, event_type: str, severity: int} or None on failure
    """
    prompt = f"""You are a geopolitical analyst screening news events for relevance to prediction markets.

EVENT:
- Headline: {event.get('title', '')}
- Type: {event.get('event_type', 'unknown')}
- Country/Region: {event.get('country', 'unknown')}
- Initial Severity: {event.get('severity', 1)}/5

PREDICTION MARKET:
- Question: {market_title}

TASK: Determine if this event is directly relevant to the prediction market question.
Rate severity 1-5 where:
  1 = No connection
  2 = Tangentially related
  3 = Moderately relevant — could shift probability
  4 = Highly relevant — likely shifts probability
  5 = Critical — directly determines outcome

Respond with ONLY this JSON (no other text):
{{"relevant": true/false, "event_type": "conflict/diplomacy/ceasefire/sanctions/military/election/other", "severity": 1-5}}"""

    result = _call_claude(prompt, model='haiku', timeout=20)
    if result is None:
        return None

    # Validate and normalize
    try:
        return {
            'relevant': bool(result.get('relevant', False)),
            'event_type': str(result.get('event_type', 'unknown')),
            'severity': max(1, min(5, int(result.get('severity', 1)))),
        }
    except (ValueError, TypeError):
        return None


def stage2_estimate(event, market_title, current_price, days_to_expiry):
    """
    Stage 2 — Sonnet estimator.
    Estimates probability a market resolves YES given a geopolitical event.

    Only called on markets that pass Stage 1 (severity >= 3).

    Args:
        event: dict with keys: title, event_type, country, severity
        market_title: Kalshi market title string
        current_price: Current YES price in cents (0-100)
        days_to_expiry: Days until market closes

    Returns:
        {estimated_prob: float, confidence: float, reasoning: str} or None
    """
    market_prob = current_price / 100 if current_price > 0 else 0.5

    prompt = f"""You are a geopolitical probability estimator for prediction markets. Be calibrated and conservative.

EVENT:
- Headline: {event.get('title', '')}
- Type: {event.get('event_type', 'unknown')}
- Country/Region: {event.get('country', 'unknown')}

PREDICTION MARKET:
- Question: {market_title}
- Current YES price: {current_price}c (market implies {market_prob:.0%} probability)
- Days to expiry: {days_to_expiry if days_to_expiry is not None else 'unknown'}

TASK: Estimate the TRUE probability this market resolves YES, given the event.

Guidelines:
- Be conservative — geopolitical events are hard to predict
- Consider the time horizon (days to expiry)
- Don't anchor too heavily on the current market price
- Your confidence should reflect how well this event informs the market question
- Confidence 0.0-1.0 where 0.5 = uncertain, 0.85 = very confident (cap at 0.85 for geo)

Respond with ONLY this JSON (no other text):
{{"estimated_prob": 0.XX, "confidence": 0.XX, "reasoning": "one sentence explanation"}}"""

    result = _call_claude(prompt, model='sonnet', timeout=45)
    if result is None:
        return None

    # Validate and normalize
    try:
        estimated_prob = float(result.get('estimated_prob', 0.5))
        confidence = float(result.get('confidence', 0.5))
        reasoning = str(result.get('reasoning', ''))

        # Clamp values
        estimated_prob = max(0.01, min(0.99, estimated_prob))
        confidence = max(0.0, min(0.85, confidence))  # Cap at 0.85 for geo

        return {
            'estimated_prob': round(estimated_prob, 3),
            'confidence': round(confidence, 3),
            'reasoning': reasoning[:200],
        }
    except (ValueError, TypeError):
        return None


def screen_and_estimate(pairs, min_severity=3):
    """
    Run the full two-stage pipeline on a list of event-market pairs.

    Args:
        pairs: list from geo_client.get_events() — [{event, market_title, market_ticker, current_price, days_to_expiry}]
        min_severity: minimum severity from Stage 1 to proceed to Stage 2 (default 3)

    Returns:
        list of dicts with LLM estimates added:
        [{
            ...original pair fields...,
            stage1: {relevant, event_type, severity},
            stage2: {estimated_prob, confidence, reasoning} or None,
            edge: float or None,
        }]
    """
    results = []
    stage1_count = 0
    stage2_count = 0

    for pair in pairs:
        event = pair.get('event', {})
        market_title = pair.get('market_title', '')
        market_ticker = pair.get('market_ticker', '')
        current_price = pair.get('current_price', 50)
        days_to_expiry = pair.get('days_to_expiry')

        # Stage 1: Haiku classification
        s1 = stage1_classify(event, market_title)
        stage1_count += 1

        if s1 is None:
            log_activity(f"[GeoEdge] Stage 1 failed for {market_ticker} — skipping")
            continue

        result = {**pair, 'stage1': s1, 'stage2': None, 'edge': None}

        if not s1['relevant'] or s1['severity'] < min_severity:
            results.append(result)
            continue

        # Stage 2: Sonnet estimation (only for severity >= min_severity)
        s2 = stage2_estimate(event, market_title, current_price, days_to_expiry)
        stage2_count += 1

        if s2 is not None:
            result['stage2'] = s2
            # Calculate edge: estimated_prob vs market-implied prob
            market_prob = current_price / 100 if current_price > 0 else 0.5
            result['edge'] = round(abs(s2['estimated_prob'] - market_prob), 4)

        results.append(result)

    # Log results
    os.makedirs(os.path.dirname(GEO_EDGE_LOG), exist_ok=True)
    with open(GEO_EDGE_LOG, 'a', encoding='utf-8') as f:
        for r in results:
            log_entry = {
                'date': str(date.today()),
                'ticker': r.get('market_ticker', ''),
                'event_title': r.get('event', {}).get('title', '')[:100],
                'stage1': r.get('stage1'),
                'stage2': r.get('stage2'),
                'edge': r.get('edge'),
            }
            f.write(json.dumps(log_entry) + '\n')

    log_activity(
        f"[GeoEdge] Screened {stage1_count} pairs → {stage2_count} passed to Stage 2 → "
        f"{sum(1 for r in results if r.get('edge') is not None)} with edge estimates"
    )
    return results


if __name__ == '__main__':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    # Test with a mock pair
    mock_pair = {
        'event': {
            'title': 'Ukraine and Russia agree to ceasefire extension',
            'event_type': 'ceasefire',
            'country': 'Ukraine',
            'severity': 4,
        },
        'market_title': 'Will a Ukraine-Russia ceasefire be in effect on April 1?',
        'market_ticker': 'KXCEASEFIRE-26APR01',
        'current_price': 35,
        'days_to_expiry': 6.0,
    }

    print("=== Stage 1: Haiku Classification ===")
    s1 = stage1_classify(mock_pair['event'], mock_pair['market_title'])
    print(json.dumps(s1, indent=2))

    if s1 and s1.get('severity', 0) >= 3:
        print("\n=== Stage 2: Sonnet Estimation ===")
        s2 = stage2_estimate(
            mock_pair['event'], mock_pair['market_title'],
            mock_pair['current_price'], mock_pair['days_to_expiry']
        )
        print(json.dumps(s2, indent=2))

    print("\n=== Full Pipeline ===")
    results = screen_and_estimate([mock_pair])
    for r in results:
        print(json.dumps({
            'ticker': r['market_ticker'],
            'stage1': r['stage1'],
            'stage2': r['stage2'],
            'edge': r['edge'],
        }, indent=2))

import httpx
from . import config

_ACTIONS = {
    "panels": "cross-check with the power budget model and consider a load shed if the trend continues.",
    "body": "flag for thermal subsystem review; verify radiator and heater cycling.",
    "sensor": "correlate with the mission radiation environment model to rule out a natural event.",
    "jitter": "command a reaction-wheel desaturation and confirm star-tracker lock.",
    "antenna": "attempt a ground-station handover and verify uplink command path.",
}


def local_template(ch: dict) -> str:
    direction = "above" if ch["z"] > 0 else "below"
    action = _ACTIONS.get(ch["part"], "escalate to subsystem engineer for review.")
    return (
        f"{ch['label']} ({ch['channel']}) is reading {abs(ch['z']):.1f}\u03c3 {direction} its rolling "
        f"nominal baseline of {ch['baseline_mean']:.2f}{ch['unit']}, with severity scored at "
        f"{ch['severity']}/100. Recommended action: {action}"
    )


async def generate_diagnosis(ch: dict):
    """Returns (narrative: str, source: 'claude' | 'local_template')."""
    if not config.ANTHROPIC_API_KEY:
        return local_template(ch), "local_template"

    prompt = (
        "You are the autonomous diagnostic assistant on a satellite health-monitoring console. "
        f"A telemetry channel crossed its anomaly threshold. Channel: {ch['label']} ({ch['channel']}), "
        f"unit: {ch['unit']}. Current value: {ch['value']:.2f}{ch['unit']}. Rolling nominal baseline: "
        f"{ch['baseline_mean']:.2f}{ch['unit']}. Deviation: {ch['z']:.2f} standard deviations. "
        f"Severity score: {ch['severity']}/100. Write a concise 2-3 sentence mission-control-style "
        "diagnosis in plain English: what is likely happening and one recommended action. "
        "No preamble, no markdown, no headers, plain sentences only."
    )
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": config.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 220,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            r.raise_for_status()
            data = r.json()
            for block in data.get("content", []):
                if block.get("type") == "text" and block.get("text"):
                    return block["text"].strip(), "claude"
    except Exception:
        pass
    return local_template(ch), "local_template"

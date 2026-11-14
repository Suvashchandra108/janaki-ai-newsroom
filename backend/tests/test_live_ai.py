"""Live Gemini check, run in CI only when the GEMINI_API_KEY secret is configured.

The key is never printed. If GEMINI_MODEL is not set, the test lists the models the key can
use and picks a Flash-Lite (else Flash) model that supports generateContent.
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.modules.ai_gateway.gateway import GEMINI_BASE, AIError, GeminiProvider
from app.modules.research.claims import extract_claims

KEY = os.environ.get("GEMINI_API_KEY", "")
pytestmark = pytest.mark.skipif(not KEY, reason="GEMINI_API_KEY not configured")

ARTICLE = (
    "Floods in Saptari district have displaced 2,000 families, the Madhesh Province government "
    "said on Friday. The Chief Minister announced relief of NPR 50 million for affected "
    "households. Rescue teams worked through the night to move residents to higher ground."
)


def _pick_model() -> str:
    if os.environ.get("GEMINI_MODEL"):
        return os.environ["GEMINI_MODEL"]
    resp = httpx.get(f"{GEMINI_BASE}/models", headers={"x-goog-api-key": KEY}, timeout=30)
    assert resp.status_code == 200, f"model listing failed: HTTP {resp.status_code}"
    names = [
        m["name"].removeprefix("models/")
        for m in resp.json().get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
    for wanted in ("flash-lite", "flash"):
        stable = [n for n in names if wanted in n and "preview" not in n and "exp" not in n]
        if stable:
            return sorted(stable)[-1]
    pytest.skip(f"no Flash model available to this key; models: {names[:10]}")


def test_real_gemini_extracts_grounded_claims() -> None:
    model = _pick_model()
    print(f"\nLive Gemini model: {model}")
    llm = GeminiProvider(api_key=KEY, model=model)
    try:
        claims, result = extract_claims(
            llm, headline="Saptari floods", article=ARTICLE, max_claims=5
        )
    except AIError as exc:
        pytest.fail(f"Gemini call failed: {exc.code} ({exc.message})")
    print(
        f"Tokens: {result.input_tokens} in / {result.output_tokens} out; "
        f"grounded claims kept: {len(claims)}"
    )
    for c in claims:
        print(f"  [{c.claim_type}] {c.text}  numbers={c.numbers}")
    assert result.input_tokens > 0
    assert claims, "model returned no grounded claims"
    assert any(n["value"] == 2000 for c in claims for n in c.numbers)


def test_real_gemini_writes_cited_english_draft() -> None:
    from app.modules.editorial.writer import ClaimRef, plan_angles, write_article

    claims = [
        ClaimRef(
            "C1",
            "id-1",
            "Floods in Saptari district displaced 2,000 families",
            "corroborated",
            "official",
            ["kathmandupost.com", "risingnepaldaily.com"],
            [
                "Floods in Saptari district have displaced 2,000 families, the Madhesh "
                "Province government said on Friday."
            ],
            [{"value": 2000, "unit": "families"}],
        ),
        ClaimRef(
            "C2",
            "id-2",
            "The Chief Minister announced NPR 50 million in relief",
            "insufficient",
            "official",
            ["kathmandupost.com"],
            ["The Chief Minister announced relief of NPR 50 million for affected households."],
            [{"value": 50, "unit": "NPR million"}],
        ),
    ]
    llm = GeminiProvider(api_key=KEY, model=_pick_model())
    try:
        plan, _ = plan_angles(llm, headline="Saptari floods", claims=claims)
        draft, result = write_article(
            llm, headline="Saptari floods", angle="straight", focus=None, claims=claims
        )
    except AIError as exc:
        pytest.fail(f"Gemini call failed: {exc.code} ({exc.message})")
    print(f"\nPlan: A={plan.a_refs} B={plan.b_refs} ({plan.b_reason})")
    print(f"Tokens: {result.input_tokens} in / {result.output_tokens} out")
    print(f"HEADLINE: {draft.headline}\nSUMMARY: {draft.summary}")
    for p in draft.paragraphs:
        print(f"  - {p['text']}  [cites {len(p['claim_ids'])}]")
    print(f"SEO: {draft.seo_title} | {draft.seo_description}")
    print(f"FLAGS: {[f['code'] for f in draft.flags]}")
    assert draft.headline and draft.paragraphs
    assert any(p["claim_ids"] for p in draft.paragraphs)
    assert len(draft.seo_title) <= 70 and len(draft.seo_description) <= 170

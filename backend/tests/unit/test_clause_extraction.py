"""Regression tests for keyword clause extraction in the default upload pipeline."""
import pytest

from backend.embeddings.agents.clause_embedding_agent import ClauseEmbeddingAgent


def _types(text):
    return {r.metadata["clause_type"] for r in ClauseEmbeddingAgent().process(text, {"file_id": "C1"})}


@pytest.mark.parametrize("text", [
    # Wording from data/Clean_MSA.pdf and data/Clean_SOW.pdf, which the old patterns missed
    "2. Payment Terms\nClient shall pay all invoices within ninety (90) days of receipt.",
    "4. Fees & Invoicing\nClient will pay invoices within 60-90 days, depending on internal processing schedules.",
    "Each invoice shall be paid within 30 days.",
    # Wording the old patterns already handled must still match
    "Payment is due within thirty (30) days of the invoice date.",
    "The invoice is payable on receipt.",
])
def test_payment_clauses_are_extracted(text):
    assert "Payment Terms" in _types(text)


def test_unrelated_text_is_not_a_payment_clause():
    assert "Payment Terms" not in _types("Company will deliver a digital modernization program, including design.")

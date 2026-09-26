from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type, Dict, Any, List, Optional
from backend.domain.entities import ContractClause, PolicyViolation, RiskAssessment, RedlineRecommendation
import json
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

# Company policy rules - merged existing with comprehensive internal policies
COMPANY_POLICIES = {
    "payment_terms": {
        "preferred_days": 30,
        "acceptable_days": 45,  # requires Delivery Director approval
        "red_flags": [60, 90],
        "redline_text": "Payment is due within thirty (30) days of invoice receipt."
    },
    "liability_cap": {
        "preferred_multiplier": 1,  # 1x total fees
        "acceptable_multiplier": 2,  # requires Legal approval
        "min_amount": 100000,  # legacy minimum
        "red_flags": ["unlimited", "indirect_damages", "consequential_damages"],
        "redline_text": "Our liability shall not exceed the total fees paid or payable under the applicable Statement of Work."
    },
    "indemnification": {
        "preferred_type": "mutual",
        "acceptable_scope": ["third_party_ip", "gross_negligence", "willful_misconduct"],
        "red_flags": ["broad_indemnification", "client_negligence", "open_ended_defense"],
        "redline_text": "Each party will indemnify the other solely for third-party claims arising from gross negligence, willful misconduct, or infringement of IP under this Agreement."
    },
    "termination": {
        "min_notice_days": 30,
        "payment_required": "work_in_progress",
        "red_flags": ["immediate_termination", "no_payment_wip"],
        "redline_text": "Either party may terminate this SOW with thirty (30) days' written notice. All completed work shall be payable upon termination."
    },
    "ip_ownership": {
        "company_retains": "pre_existing_ip",
        "client_owns": "deliverables",
        "red_flags": ["client_claims_company_ip", "assignment_without_carveouts"],
        "redline_text": "Client owns deliverables created specifically for the engagement. Company retains ownership of its pre-existing IP, reusable tools, and methodologies."
    },
    "confidentiality": {
        "required": True,
        "mutual": True,
        "redline_text": "Both parties agree to maintain confidentiality of all proprietary information."
    }
}

def _is_ip_clause(clause_type: str) -> bool:
    """True for IP clauses; avoids matching 'ip' inside Shipping/Relationship/Membership."""
    import re
    lower = clause_type.lower()
    return bool(re.search(r"\bip\b", lower)) or "intellectual property" in lower


# Clause Extraction Agent Tools
class ClauseDetectorInput(BaseModel):
    contract_text: str = Field(description="Contract text to analyze for clauses")


CLAUSE_TYPES = [
    "Payment Terms", "Liability", "Indemnification", "Confidentiality",
    "Termination", "IP Ownership", "Governing Law", "Warranty", "Auto-Renewal",
    "Non-Compete", "Exclusivity", "Data Protection",
]

# Keyword heuristics used when no LLM is available (and as a safety net when
# the LLM call fails). Each entry: clause type -> (trigger regexes, HIGH-risk regexes)
_CLAUSE_RULES = {
    "Payment Terms": ([r"\bpayment\b", r"\binvoice", r"\bnet\s*\d{2}\b", r"\bfees?\s+(are|shall be)\s+(due|payable)"],
                      [r"\bnet\s*(60|90|120)\b", r"\b(60|90|120)\s+days\b"]),
    "Liability": ([r"\bliabilit", r"\bconsequential damages\b", r"\bindirect damages\b"],
                  [r"\bunlimited liability\b", r"\bno limitation\b", r"\bconsequential damages\b"]),
    "Indemnification": ([r"\bindemnif", r"\bhold harmless\b"],
                        [r"\bany and all claims\b", r"\bnegligence of (the )?client\b"]),
    "Confidentiality": ([r"\bconfidential", r"\bnon-disclosure\b"], [r"\bperpetual(ly)?\b"]),
    "Termination": ([r"\bterminat"], [r"\bimmediate(ly)? terminat", r"\bwithout (prior )?notice\b"]),
    "IP Ownership": ([r"\bintellectual property\b", r"\bwork made for hire\b", r"\bassigns? all (right|title)"],
                     [r"\bassigns? all (right|title)", r"\bpre-existing\b.*\bassign"]),
    "Governing Law": ([r"\bgoverned by\b", r"\bgoverning law\b", r"\bjurisdiction\b"], []),
    "Warranty": ([r"\bwarrant(y|ies|s)\b"], [r"\bas is\b", r"\bdisclaims? all warrant"]),
    "Auto-Renewal": ([r"\bautomatically renew", r"\bauto-renew"], [r"\bautomatically renew"]),
    "Non-Compete": ([r"\bnon-?compet", r"\bshall not compete\b"], [r"\bnon-?compet"]),
    "Exclusivity": ([r"\bexclusiv"], [r"\bexclusive\b"]),
    "Data Protection": ([r"\bpersonal data\b", r"\bgdpr\b", r"\bdata protection\b"], [r"\bindefinitely\b"]),
}


def _split_sentences(text: str) -> List[str]:
    import re
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z0-9(])|\n{2,}", text)
    return [p.strip() for p in parts if len(p.strip()) > 25]


def extract_clauses_heuristic(contract_text: str, max_per_type: int = 2) -> List[Dict[str, Any]]:
    """Deterministic keyword-based clause extraction from the actual contract text."""
    import re
    sentences = _split_sentences(contract_text)
    clauses: List[Dict[str, Any]] = []
    for clause_type, (triggers, high_risk) in _CLAUSE_RULES.items():
        found = 0
        for idx, sentence in enumerate(sentences):
            lower = sentence.lower()
            if not any(re.search(t, lower) for t in triggers):
                continue
            risk = "HIGH" if any(re.search(h, lower) for h in high_risk) else "MEDIUM" if clause_type in (
                "Liability", "Indemnification", "IP Ownership", "Termination") else "LOW"
            clauses.append({
                "clause_type": clause_type,
                "content": sentence[:1000],
                "risk_level": risk,
                "confidence_score": 0.6,
                "location": f"Sentence {idx + 1}",
                "extraction_method": "heuristic",
            })
            found += 1
            if found >= max_per_type:
                break
    return clauses


class ClauseDetectorTool(BaseTool):
    name: str = "clause_detector"
    description: str = "Detect and extract key contract clauses"
    args_schema: Type[BaseModel] = ClauseDetectorInput
    # Optional chat model. Without one (or if the call fails) the tool falls back
    # to keyword heuristics over the real text - it never returns canned clauses.
    llm: Optional[Any] = Field(default=None, exclude=True)

    WINDOW_CHARS: int = 8000
    MAX_WINDOWS: int = 4

    def _run(self, contract_text: str) -> str:
        """Extract clauses from contract text"""
        if not contract_text or not contract_text.strip():
            return json.dumps([])
        clauses: List[Dict[str, Any]] = []
        if self.llm is not None:
            try:
                clauses = self._extract_with_llm(contract_text)
            except Exception as e:
                logger.error(f"LLM clause extraction failed, using heuristics: {e}")
        if not clauses:
            clauses = extract_clauses_heuristic(contract_text)
        logger.info(f"Extracted {len(clauses)} clauses")
        return json.dumps(clauses)

    def _extract_with_llm(self, contract_text: str) -> List[Dict[str, Any]]:
        from backend.governance.llm_judge import _extract_json

        windows = [contract_text[i:i + self.WINDOW_CHARS]
                   for i in range(0, len(contract_text), self.WINDOW_CHARS)][: self.MAX_WINDOWS]
        results: List[Dict[str, Any]] = []
        seen = set()
        for n, window in enumerate(windows, 1):
            prompt = (
                "Extract the key clauses from this contract excerpt. Quote clause text verbatim.\n"
                f"Allowed clause_type values: {', '.join(CLAUSE_TYPES)}.\n"
                "risk_level is one of LOW, MEDIUM, HIGH, CRITICAL from the perspective of the service provider.\n"
                'Respond ONLY with JSON: {"clauses": [{"clause_type": "...", "content": "...", '
                '"risk_level": "...", "confidence_score": 0.0-1.0, "location": "section number or heading"}]}\n\n'
                f"Excerpt {n}/{len(windows)}:\n{window}"
            )
            response = self.llm.invoke(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            if isinstance(raw, list):
                raw = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in raw)
            data = _extract_json(raw)
            items = data.get("clauses", []) if isinstance(data, dict) else data
            for item in items or []:
                content = str(item.get("content", "")).strip()
                ctype = str(item.get("clause_type", "")).strip()
                key = (ctype.lower(), content[:80].lower())
                if not content or key in seen:
                    continue
                seen.add(key)
                risk = str(item.get("risk_level", "MEDIUM")).upper()
                try:
                    confidence = max(0.0, min(1.0, float(item.get("confidence_score", 0.7))))
                except (TypeError, ValueError):
                    confidence = 0.7
                results.append({
                    "clause_type": ctype or "General",
                    "content": content[:2000],
                    "risk_level": risk if risk in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else "MEDIUM",
                    "confidence_score": confidence,
                    "location": str(item.get("location", "")),
                    "extraction_method": "llm",
                })
        return results

# Policy Compliance Agent Tools
class PolicyCheckerInput(BaseModel):
    clauses_json: str = Field(description="JSON string of extracted clauses")

class PolicyCheckerTool(BaseTool):
    name: str = "policy_checker"
    description: str = "Check clauses against company policies"
    args_schema: Type[BaseModel] = PolicyCheckerInput
    
    def _run(self, clauses_json: str) -> str:
        """Check clauses against policies"""
        try:
            clauses = json.loads(clauses_json)
            violations = []
            
            for clause in clauses:
                clause_type = clause.get("clause_type", "").lower()
                content = clause.get("content", "").lower()
                
                # Check payment terms against company policy
                if "payment" in clause_type:
                    if any(term in content for term in ["60 days", "90 days", "net 60", "net 90"]):
                        violations.append({
                            "clause_type": clause["clause_type"],
                            "issue": "Payment terms exceed company policy (Net 30 preferred, Net 45 max with approval)",
                            "severity": "CRITICAL",
                            "suggested_fix": COMPANY_POLICIES["payment_terms"]["redline_text"],
                            "clause_content": clause["content"]
                        })
                    elif any(term in content for term in ["45 days", "net 45"]):
                        violations.append({
                            "clause_type": clause["clause_type"],
                            "issue": "Payment terms require Delivery Director approval (Net 45)",
                            "severity": "MEDIUM",
                            "suggested_fix": "Obtain Delivery Director approval or " + COMPANY_POLICIES["payment_terms"]["redline_text"],
                            "clause_content": clause["content"]
                        })
                
                # Check liability caps against company policy
                if "liability" in clause_type:
                    if any(term in content for term in ["unlimited", "indirect", "consequential", "special damages"]):
                        violations.append({
                            "clause_type": clause["clause_type"],
                            "issue": "Liability policy violation - unlimited or indirect/consequential damages exposure",
                            "severity": "CRITICAL",
                            "suggested_fix": COMPANY_POLICIES["liability_cap"]["redline_text"],
                            "clause_content": clause["content"]
                        })
                    elif any(amount in content for amount in ["50,000", "25,000", "$50k", "$25k"]):
                        violations.append({
                            "clause_type": clause["clause_type"],
                            "issue": "Liability cap not linked to SOW fees and below minimum threshold",
                            "severity": "HIGH",
                            "suggested_fix": COMPANY_POLICIES["liability_cap"]["redline_text"],
                            "clause_content": clause["content"]
                        })
                
                # Check indemnification against company policy
                if "indemnif" in clause_type.lower() or "indemnit" in content:
                    if any(term in content for term in ["broad", "client negligence", "misuse", "open-ended"]):
                        violations.append({
                            "clause_type": "Indemnification",
                            "issue": "Broad indemnification or client negligence coverage violates company policy",
                            "severity": "CRITICAL",
                            "suggested_fix": COMPANY_POLICIES["indemnification"]["redline_text"],
                            "clause_content": clause["content"]
                        })
                
                # Check termination against company policy
                if "terminat" in clause_type.lower():
                    if any(term in content for term in ["immediate", "no notice", "0 days"]):
                        violations.append({
                            "clause_type": clause["clause_type"],
                            "issue": "Immediate termination without notice violates company policy",
                            "severity": "HIGH",
                            "suggested_fix": COMPANY_POLICIES["termination"]["redline_text"],
                            "clause_content": clause["content"]
                        })
                
                # Check IP ownership against company policy
                if _is_ip_clause(clause_type):
                    if any(term in content for term in ["client owns all", "assignment of rights", "company ip to client"]):
                        violations.append({
                            "clause_type": clause["clause_type"],
                            "issue": "IP assignment without carve-outs for company pre-existing IP",
                            "severity": "CRITICAL",
                            "suggested_fix": COMPANY_POLICIES["ip_ownership"]["redline_text"],
                            "clause_content": clause["content"]
                        })
            
            logger.info(f"Found {len(violations)} policy violations")
            return json.dumps(violations)
            
        except Exception as e:
            logger.error(f"Policy checking failed: {e}")
            return json.dumps([])

# Risk Assessment Agent Tools
class RiskCalculatorInput(BaseModel):
    clauses_json: str = Field(description="JSON string of clauses")
    violations_json: str = Field(description="JSON string of violations")

class RiskCalculatorTool(BaseTool):
    name: str = "risk_calculator"
    description: str = "Calculate overall contract risk score"
    args_schema: Type[BaseModel] = RiskCalculatorInput
    
    def _run(self, clauses_json: str, violations_json: str) -> str:
        """Calculate risk assessment"""
        try:
            clauses = json.loads(clauses_json)
            violations = json.loads(violations_json)
            
            if not clauses and not violations:
                # Nothing was extracted: do not report a fabricated baseline score
                return json.dumps({
                    "overall_risk_score": 0.0,
                    "risk_level": "UNKNOWN",
                    "critical_issues": [],
                    "recommendations": ["No clauses could be extracted - manual review required"]
                })

            # Calculate base risk from clauses
            risk_score = 30.0  # Base risk
            
            # Add risk from violations
            for violation in violations:
                severity = violation.get("severity", "LOW")
                if severity == "CRITICAL":
                    risk_score += 25
                elif severity == "HIGH":
                    risk_score += 15
                elif severity == "MEDIUM":
                    risk_score += 10
                else:
                    risk_score += 5
            
            # Cap at 100
            risk_score = min(risk_score, 100.0)
            
            # Determine risk level
            if risk_score >= 80:
                risk_level = "CRITICAL"
            elif risk_score >= 60:
                risk_level = "HIGH"
            elif risk_score >= 40:
                risk_level = "MEDIUM"
            else:
                risk_level = "LOW"
            
            # Generate recommendations
            recommendations = []
            if len(violations) > 0:
                recommendations.append("Address policy violations before signing")
            if risk_score > 70:
                recommendations.append("Requires legal review and approval")
            
            critical_issues = [v["issue"] for v in violations if v.get("severity") == "CRITICAL"]
            
            assessment = {
                "overall_risk_score": risk_score,
                "risk_level": risk_level,
                "critical_issues": critical_issues,
                "recommendations": recommendations
            }
            
            logger.info(f"Risk assessment: {risk_level} ({risk_score}/100)")
            return json.dumps(assessment)
            
        except Exception as e:
            logger.error(f"Risk calculation failed: {e}")
            return json.dumps({"overall_risk_score": 50.0, "risk_level": "MEDIUM", "critical_issues": [], "recommendations": []})

# Redline Generation Agent Tools
class RedlineGeneratorInput(BaseModel):
    violations_json: str = Field(description="JSON string of policy violations")

class RedlineGeneratorTool(BaseTool):
    name: str = "redline_generator"
    description: str = "Generate redline recommendations for violations"
    args_schema: Type[BaseModel] = RedlineGeneratorInput
    
    def _run(self, violations_json: str) -> str:
        """Generate redline recommendations"""
        try:
            violations = json.loads(violations_json)
            redlines = []
            
            for violation in violations:
                clause_type = violation.get("clause_type", "")
                issue = violation.get("issue", "")
                suggested_fix = violation.get("suggested_fix", "")
                original_text = violation.get("clause_content", "")
                
                if "payment" in clause_type.lower():
                    redlines.append({
                        "original_text": original_text,
                        "suggested_text": COMPANY_POLICIES["payment_terms"]["redline_text"],
                        "justification": "Aligns with company payment policy (Net 30 preferred)",
                        "priority": "HIGH"
                    })
                
                elif "liability" in clause_type.lower():
                    redlines.append({
                        "original_text": original_text,
                        "suggested_text": COMPANY_POLICIES["liability_cap"]["redline_text"],
                        "justification": "Caps liability at 1x SOW fees per company policy",
                        "priority": "CRITICAL"
                    })
                
                elif "indemnif" in clause_type.lower():
                    redlines.append({
                        "original_text": original_text,
                        "suggested_text": COMPANY_POLICIES["indemnification"]["redline_text"],
                        "justification": "Limits indemnification to mutual third-party claims only",
                        "priority": "CRITICAL"
                    })
                
                elif "terminat" in clause_type.lower():
                    redlines.append({
                        "original_text": original_text,
                        "suggested_text": COMPANY_POLICIES["termination"]["redline_text"],
                        "justification": "Ensures 30-day notice and payment for work-in-progress",
                        "priority": "HIGH"
                    })
                
                elif _is_ip_clause(clause_type):
                    redlines.append({
                        "original_text": original_text,
                        "suggested_text": COMPANY_POLICIES["ip_ownership"]["redline_text"],
                        "justification": "Protects company pre-existing IP and methodologies",
                        "priority": "CRITICAL"
                    })

                elif suggested_fix:
                    # Violations from other checks (e.g. CUAD deviations) carry their own fix
                    redlines.append({
                        "original_text": original_text,
                        "suggested_text": suggested_fix,
                        "justification": issue or "Addresses detected policy deviation",
                        "priority": violation.get("severity", "MEDIUM") if violation.get("severity") in ("LOW", "MEDIUM", "HIGH", "CRITICAL") else "MEDIUM"
                    })
            
            logger.info(f"Generated {len(redlines)} redline recommendations")
            return json.dumps(redlines)
            
        except Exception as e:
            logger.error(f"Redline generation failed: {e}")
            return json.dumps([])
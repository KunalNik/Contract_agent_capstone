"""
Section Extraction Agent
Strategy Pattern + Observer Pattern for document section extraction
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import re
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

@dataclass
class Section:
    """Section data model with order preservation"""
    title: str
    content: str
    order: int
    start_position: int  # Character position in original text
    end_position: int    # End character position
    section_type: str = "general"
    confidence: float = 1.0

class ISectionExtractionStrategy(ABC):
    """Strategy interface for section extraction"""
    
    @abstractmethod
    def extract_sections(self, text: str) -> List[Section]:
        """Extract sections from text"""
        pass

class RegexSectionExtractor(ISectionExtractionStrategy):
    """Fast regex-based section extraction"""
    
    def extract_sections(self, text: str) -> List[Section]:
        """Extract sections using regex patterns"""
        sections = []
        
        # Common section patterns. Case-sensitive on purpose: with IGNORECASE
        # the ALL-CAPS rule matched every short line ("the parties agree").
        patterns = [
            re.compile(r'^\s*(\d+(\.\d+)*\.?\s+[A-Z][^\n]{2,80})\s*$'),   # "1. Payment Terms"
            re.compile(r'^\s*([A-Z][A-Z0-9&,\-\s]{4,60})\s*$'),              # "PAYMENT TERMS"
            re.compile(r'^\s*((ARTICLE|Article|SECTION|Section)\s+[IVXLC\d]+\b[^\n]{0,60})\s*$'),
        ]
        
        lines = text.split('\n')
        current_section = None
        content_buffer = []
        order = 0
        
        for line in lines:
            is_section_header = False
            
            stripped = line.strip()
            for pattern in patterns:
                # Headings are short; long numbered lines are clauses, not headers
                if len(stripped) <= 90 and pattern.match(stripped):
                    # Save previous section
                    if current_section:
                        sections.append(Section(
                            title=current_section,
                            content='\n'.join(content_buffer).strip(),
                            order=order,
                            start_position=0,  # Will be calculated properly
                            end_position=0,    # Will be calculated properly
                            confidence=0.8
                        ))
                        order += 1
                    
                    # Start new section
                    current_section = line.strip()
                    content_buffer = []
                    is_section_header = True
                    break
            
            if not is_section_header and current_section:
                content_buffer.append(line)
        
        # Add final section
        if current_section and content_buffer:
            sections.append(Section(
                title=current_section,
                content='\n'.join(content_buffer).strip(),
                order=order,
                start_position=0,  # Will be calculated properly
                end_position=0,    # Will be calculated properly
                confidence=0.8
            ))
        
        # Fill in character offsets (previously always 0)
        cursor = 0
        for section in sections:
            start = text.find(section.title, cursor)
            if start == -1:
                continue
            section.start_position = start
            section.end_position = start + len(section.title) + len(section.content) + 1
            cursor = start + len(section.title)
        return sections

class LLMSectionExtractor(ISectionExtractionStrategy):
    """LLM-based intelligent section extraction"""
    
    def __init__(self, llm):
        self.llm = llm
    
    def extract_sections(self, text: str) -> List[Section]:
        """Extract sections using LLM analysis"""
        # Truncate for LLM processing
        analysis_text = text[:6000] if len(text) > 6000 else text
        
        prompt = f"""
        Analyze this contract and identify major sections. Return a JSON list of sections:
        
        {analysis_text}
        
        Format: [{{"title": "Section Title", "start_marker": "text snippet", "type": "recitals|definitions|terms|termination|general"}}]
        
        Focus on major structural sections, not individual clauses.
        """
        
        try:
            response = self.llm.invoke(prompt)
            # Parse LLM response and extract sections
            # Implementation would parse JSON and map to text
            return self._parse_llm_response(response.content, text)
        except Exception as e:
            logger.error(f"LLM section extraction failed: {e}")
            return []
    
    def _parse_llm_response(self, response, full_text: str) -> List[Section]:
        """Parse the LLM's JSON list and slice the real text between section markers."""
        from backend.governance.llm_judge import _extract_json
        if isinstance(response, list):
            response = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in response)
        try:
            data = _extract_json(response if response.strip().startswith(("{", "`")) else f'{{"s": {response}}}')
        except Exception as e:
            logger.error(f"Could not parse LLM section output: {e}")
            return []
        items = data.get("s") or data.get("sections") or [] if isinstance(data, dict) else data
        located = []
        for item in items or []:
            marker = str(item.get("start_marker") or item.get("title") or "").strip()
            pos = full_text.find(marker[:60]) if marker else -1
            if pos != -1:
                located.append((pos, item))
        located.sort(key=lambda x: x[0])
        sections = []
        for order, (pos, item) in enumerate(located):
            end = located[order + 1][0] if order + 1 < len(located) else len(full_text)
            sections.append(Section(
                title=str(item.get("title") or marker)[:200],
                content=full_text[pos:end].strip(),
                order=order,
                start_position=pos,
                end_position=end,
                section_type=str(item.get("type") or "general"),
                confidence=0.85,
            ))
        return sections

class HybridSectionExtractor(ISectionExtractionStrategy):
    """Hybrid approach combining regex and LLM"""
    
    def __init__(self, llm):
        self.regex_extractor = RegexSectionExtractor()
        self.llm_extractor = LLMSectionExtractor(llm)
    
    def extract_sections(self, text: str) -> List[Section]:
        """Use regex first, LLM for validation/enhancement"""
        regex_sections = self.regex_extractor.extract_sections(text)
        
        if len(regex_sections) >= 3:  # Good regex extraction
            return regex_sections
        else:  # Fallback to LLM
            return self.llm_extractor.extract_sections(text)

class SectionExtractionAgent:
    """Main section extraction agent using Strategy pattern"""
    
    def __init__(self, llm, strategy: str = "hybrid"):
        self.llm = llm
        self.strategy = self._create_strategy(strategy)
        self.observers = []
    
    def _create_strategy(self, strategy_type: str) -> ISectionExtractionStrategy:
        """Factory method for strategy creation"""
        if strategy_type == "regex":
            return RegexSectionExtractor()
        elif strategy_type == "llm":
            return LLMSectionExtractor(self.llm)
        elif strategy_type == "hybrid":
            return HybridSectionExtractor(self.llm)
        else:
            raise ValueError(f"Unknown strategy: {strategy_type}")
    
    def add_observer(self, observer):
        """Observer pattern for progress tracking"""
        self.observers.append(observer)
    
    def _notify_observers(self, event: str, data: Any):
        """Notify observers of extraction progress"""
        for observer in self.observers:
            observer.on_section_extraction_event(event, data)
    
    def extract_sections(self, text: str, contract_id: str) -> List[Dict[str, Any]]:
        """Extract sections and return as dictionaries for storage"""
        try:
            self._notify_observers("extraction_started", {"contract_id": contract_id})
            
            sections = self.strategy.extract_sections(text)
            
            # Sort sections by order to ensure correct sequence
            sections = sorted(sections, key=lambda x: x.order)
            
            # Convert to storage format
            section_dicts = []
            for section in sections:
                section_dict = {
                    "section_id": f"{contract_id}_section_{section.order:03d}",
                    "title": section.title,
                    "content": section.content,
                    "order": section.order,
                    "start_position": section.start_position,
                    "end_position": section.end_position,
                    "section_type": section.section_type,
                    "confidence": section.confidence,
                    "contract_id": contract_id
                }
                section_dicts.append(section_dict)
            
            self._notify_observers("extraction_completed", {
                "contract_id": contract_id,
                "sections_found": len(sections)
            })
            
            return section_dicts
            
        except Exception as e:
            self._notify_observers("extraction_failed", {
                "contract_id": contract_id,
                "error": str(e)
            })
            logger.error(f"Section extraction failed for {contract_id}: {e}")
            return []

class SectionExtractionObserver:
    """Observer for section extraction events"""
    
    def on_section_extraction_event(self, event: str, data: Dict[str, Any]):
        """Handle section extraction events"""
        logger.info(f"Section extraction event: {event} - {data}")
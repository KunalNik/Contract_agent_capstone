import re
from .base_strategy import IChunkingStrategy, ChunkResult
from typing import List, Dict, Any

class SentenceAdaptiveStrategy(IChunkingStrategy):
    def __init__(self, base_size: int = 1000, max_chunk_size: int = None, min_chunk_size: int = None, **kwargs):
        # Other strategies (and HybridStrategy/ChunkingAgent) pass
        # (min_chunk_size, max_chunk_size); accepting only base_size made the
        # hybrid/"auto" strategy crash on construction.
        if isinstance(max_chunk_size, int):
            base_size = max_chunk_size
        elif isinstance(min_chunk_size, int) and min_chunk_size > base_size:
            base_size = min_chunk_size
        self.base_size = base_size
        self.min_chunk_size = min_chunk_size or base_size // 2
        self.max_chunk_size = base_size
    
    def chunk_document(self, content: str, metadata: Dict[str, Any]) -> List[ChunkResult]:
        # Adaptive overlap: 50% large docs, 20% small docs
        overlap_ratio = 0.5 if len(content) > 10000 else 0.2
        
        sentences = self._split_sentences(content)
        chunks = []
        current_sentences = []
        current_length = 0
        
        for sentence in sentences:
            if current_length + len(sentence) > self.base_size and current_sentences:
                # Create chunk
                chunk = self._create_chunk(current_sentences, len(chunks))
                chunks.append(chunk)
                
                # Calculate overlap for next chunk
                overlap_count = max(1, int(len(current_sentences) * overlap_ratio))
                current_sentences = current_sentences[-overlap_count:]
                current_length = sum(len(s) for s in current_sentences)
            
            current_sentences.append(sentence)
            current_length += len(sentence)
        
        # Final chunk
        if current_sentences:
            chunks.append(self._create_chunk(current_sentences, len(chunks)))
        
        return chunks
    
    def _split_sentences(self, content: str) -> List[str]:
        # Simple sentence splitting for legal documents
        sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', content)
        
        # Filter out common legal abbreviations that shouldn't end sentences
        legal_abbrevs = ['Inc.', 'Corp.', 'LLC.', 'Ltd.', 'vs.', 'etc.', 'i.e.', 'e.g.']
        
        # Rejoin sentences that were split on abbreviations
        cleaned_sentences = []
        i = 0
        while i < len(sentences):
            sentence = sentences[i].strip()
            
            # Check if this sentence ends with a legal abbreviation
            if any(sentence.endswith(abbrev) for abbrev in legal_abbrevs) and i + 1 < len(sentences):
                # Rejoin with next sentence
                sentence = sentence + ' ' + sentences[i + 1].strip()
                i += 2
            else:
                i += 1
            
            if sentence:
                cleaned_sentences.append(sentence)
        
        return cleaned_sentences
    
    def _create_chunk(self, sentences: List[str], index: int) -> ChunkResult:
        content = " ".join(sentences)
        return ChunkResult(
            chunk_id=f"chunk_{index}",
            content=content,
            chunk_type="sentence_adaptive",
            start_pos=0,
            end_pos=len(content),
            confidence=0.95,
            overlap_with=[f"chunk_{index-1}"] if index > 0 else []
        )
    
    def chunk_text(self, text: str, metadata: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Chunk text method for compatibility with orchestrator."""
        chunk_results = self.chunk_document(text, metadata or {})
        return [
            {
                'chunk_id': chunk.chunk_id,
                'content': chunk.content,
                'chunk_type': chunk.chunk_type,
                'start_position': chunk.start_pos,
                'end_position': chunk.end_pos,
                'size': len(chunk.content),
                'confidence': chunk.confidence,
                'has_overlap': len(chunk.overlap_with) > 0,
                'overlap_with': chunk.overlap_with
            }
            for chunk in chunk_results
        ]
    
    def get_chunk_size(self) -> int:
        return self.base_size
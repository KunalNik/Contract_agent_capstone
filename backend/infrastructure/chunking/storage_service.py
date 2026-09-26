"""Enhanced storage service for chunked documents with embedding integration."""

from typing import List, Dict, Any, Optional
from backend.shared.utils.contract_search_tool import graph
from backend.infrastructure.chunking.chunk_embedding_service import ChunkEmbeddingService
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)


class ChunkingStorageService:
    """Enhanced service for storing and retrieving chunked documents with embeddings."""
    
    def __init__(self):
        self.graph = graph
        self.chunk_embedding_service = ChunkEmbeddingService()
    
    async def store_chunks(self, document_id: str, chunks: List[Dict[str, Any]], 
                         metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """Store chunks in Neo4j database with enhanced metadata.

        ``document_id`` should be the contract's file_id; the Document node is
        tagged with the tenant and linked to the Contract so chunk search can
        filter by tenant (it previously never matched: tenant was never set).
        """
        if not chunks:
            return {'success': True, 'document_id': document_id, 'chunks_stored': 0,
                    'message': 'No chunks to store'}
        tenant_id = (metadata or {}).get('tenant_id', 'default-tenant')
        try:
            # First, ensure document exists with enhanced metadata
            doc_query = """
            MERGE (d:Document {id: $document_id})
            SET d.tenant_id = $tenant_id,
                d.chunk_count = $chunk_count,
                d.chunking_metadata = $metadata,
                d.last_chunked = datetime(),
                d.chunking_strategy = $strategy,
                d.avg_chunk_size = $avg_chunk_size,
                d.total_chunks = $total_chunks
            WITH d
            OPTIONAL MATCH (c:Contract {file_id: $document_id, tenant_id: $tenant_id})
            FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END | MERGE (c)-[:HAS_DOCUMENT]->(d))
            """
            
            # Calculate average chunk size
            avg_chunk_size = sum(chunk.get('size', len(chunk['content'])) for chunk in chunks) / len(chunks)
            strategy_used = chunks[0].get('chunk_type', 'unknown') if chunks else 'unknown'
            
            import json
            self.graph.query(doc_query, {
                'document_id': document_id,
                'tenant_id': tenant_id,
                'chunk_count': len(chunks),
                'metadata': json.dumps(metadata or {}),
                'strategy': strategy_used,
                'avg_chunk_size': avg_chunk_size,
                'total_chunks': len(chunks)
            })
                
            # Re-chunking replaces previous chunks instead of duplicating them
            self.graph.query(
                "MATCH (:Document {id: $document_id})-[:HAS_CHUNK]->(old:Chunk) DETACH DELETE old",
                {'document_id': document_id},
            )

            # Store each chunk with enhanced properties
            for index, chunk in enumerate(chunks):
                chunk_query = """
                MATCH (d:Document {id: $document_id})
                CREATE (c:Chunk {
                    id: $chunk_id,
                    content: $content,
                    start_position: $start_position,
                    end_position: $end_position,
                    chunk_type: $chunk_type,
                    size: $size,
                    chunk_index: $chunk_index,
                    quality_score: $quality_score,
                    has_overlap: $has_overlap,
                    overlap_size: $overlap_size,
                    embedding_ready: $embedding_ready,
                    created_at: datetime(),
                    parent_section: $parent_section,
                    clause_count: $clause_count
                })
                CREATE (d)-[:HAS_CHUNK {index: $chunk_index}]->(c)
                """
                
                chunk_id = f"{document_id}_chunk_{chunk.get('chunk_index', index)}"
                
                self.graph.query(chunk_query, {
                    'document_id': document_id,
                    'chunk_id': chunk_id,
                    'content': chunk['content'],
                    'start_position': chunk.get('start_position', 0),
                    'end_position': chunk.get('end_position', 0),
                    'chunk_type': chunk.get('chunk_type', 'unknown'),
                    'size': chunk.get('size', len(chunk['content'])),
                    'chunk_index': chunk.get('chunk_index', index),
                    'quality_score': chunk.get('quality_score', 0.0),
                    'has_overlap': chunk.get('has_overlap', False),
                    'overlap_size': chunk.get('overlap_size', 0),
                    'embedding_ready': chunk.get('embedding_ready', True),
                    'parent_section': chunk.get('parent_section', ''),
                    'clause_count': chunk.get('clause_count', 0)
                })
            
            return {
                'success': True,
                'document_id': document_id,
                'chunks_stored': len(chunks),
                'avg_chunk_size': avg_chunk_size,
                'strategy_used': strategy_used,
                'message': f'Successfully stored {len(chunks)} chunks for document {document_id}'
            }
            
        except Exception as e:
            logger.error(f"Failed to store chunks for document {document_id}: {e}")
            return {
                'success': False,
                'error': str(e),
                'message': f'Failed to store chunks for document {document_id}'
            }
    
    async def get_chunks(self, document_id: str, include_embeddings: bool = False) -> List[Dict[str, Any]]:
        """Retrieve all chunks for a document with optional embeddings."""
        try:
            if include_embeddings:
                query = """
                MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
                RETURN c.id as chunk_id, c.content as content, 
                       c.start_position as start_position, c.end_position as end_position,
                       c.chunk_type as chunk_type, c.size as size,
                       c.chunk_index as chunk_index, c.quality_score as quality_score,
                       c.has_overlap as has_overlap, c.overlap_size as overlap_size,
                       c.embedding as embedding, c.embedding_ready as embedding_ready,
                       c.parent_section as parent_section, c.clause_count as clause_count
                ORDER BY c.chunk_index
                """
            else:
                query = """
                MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
                RETURN c.id as chunk_id, c.content as content, 
                       c.start_position as start_position, c.end_position as end_position,
                       c.chunk_type as chunk_type, c.size as size,
                       c.chunk_index as chunk_index, c.quality_score as quality_score,
                       c.has_overlap as has_overlap, c.overlap_size as overlap_size,
                       c.embedding_ready as embedding_ready,
                       c.parent_section as parent_section, c.clause_count as clause_count
                ORDER BY c.chunk_index
                """
            
            result = self.graph.query(query, {'document_id': document_id})
                
            chunks = []
            for record in result:
                chunk_data = {
                    'chunk_id': record['chunk_id'],
                    'content': record['content'],
                    'start_position': record['start_position'],
                    'end_position': record['end_position'],
                    'chunk_type': record['chunk_type'],
                    'size': record['size'],
                    'chunk_index': record['chunk_index'],
                    'quality_score': record['quality_score'],
                    'has_overlap': record['has_overlap'],
                    'overlap_size': record['overlap_size'],
                    'embedding_ready': record['embedding_ready'],
                    'parent_section': record['parent_section'],
                    'clause_count': record['clause_count']
                }
                
                if include_embeddings and 'embedding' in record:
                    chunk_data['embedding'] = record['embedding']
                
                chunks.append(chunk_data)
            
            return chunks
                
        except Exception as e:
            logger.error(f"Failed to retrieve chunks for document {document_id}: {e}")
            return []
    
    async def search_chunks(self, query: str, document_id: Optional[str] = None, 
                          limit: int = 10, use_embeddings: bool = True) -> List[Dict[str, Any]]:
        """Enhanced search chunks with semantic capabilities by default."""
        try:
            # Always try semantic search first for better results
            if use_embeddings:
                semantic_results = await self.chunk_embedding_service.search_similar_chunks(
                    query, document_id, limit, similarity_threshold=0.7
                )
                
                if semantic_results:
                    return semantic_results
            
            # Fallback to enhanced text search
            return await self._text_search_chunks(query, document_id, limit)
                
        except Exception as e:
            logger.error(f"Failed to search chunks: {e}")
            # Final fallback to basic text search
            return await self._basic_text_search(query, document_id, limit)
    
    async def _text_search_chunks(self, query: str, document_id: Optional[str] = None, 
                                limit: int = 10) -> List[Dict[str, Any]]:
        """Text-based chunk search fallback."""
        try:
            if document_id:
                cypher_query = """
                MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
                WHERE c.content CONTAINS $query
                RETURN c.id as chunk_id, c.content as content,
                       c.chunk_type as chunk_type, c.quality_score as quality_score,
                       c.start_position as start_position, c.end_position as end_position
                ORDER BY c.quality_score DESC, c.chunk_index ASC
                LIMIT $limit
                """
                params = {'document_id': document_id, 'query': query, 'limit': limit}
            else:
                cypher_query = """
                MATCH (c:Chunk)
                WHERE c.content CONTAINS $query
                RETURN c.id as chunk_id, c.content as content,
                       c.chunk_type as chunk_type, c.quality_score as quality_score,
                       c.start_position as start_position, c.end_position as end_position
                ORDER BY c.quality_score DESC
                LIMIT $limit
                """
                params = {'query': query, 'limit': limit}
            
            result = self.graph.query(cypher_query, params)
            
            chunks = []
            for record in result:
                chunks.append({
                    'chunk_id': record['chunk_id'],
                    'content': record['content'],
                    'chunk_type': record['chunk_type'],
                    'quality_score': record['quality_score'],
                    'start_position': record['start_position'],
                    'end_position': record['end_position'],
                    'similarity_score': 1.0  # Default for text search
                })
            
            return chunks
                
        except Exception as e:
            logger.error(f"Failed to perform text search: {e}")
            return []
    
    async def _basic_text_search(self, query: str, document_id: Optional[str] = None, 
                               limit: int = 10) -> List[Dict[str, Any]]:
        """Basic text search as final fallback."""
        try:
            if document_id:
                cypher_query = """
                MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
                WHERE toLower(c.content) CONTAINS toLower($query)
                RETURN c.id as chunk_id, c.content as content,
                       c.chunk_type as chunk_type, c.quality_score as quality_score
                ORDER BY c.quality_score DESC
                LIMIT $limit
                """
                params = {'document_id': document_id, 'query': query, 'limit': limit}
            else:
                cypher_query = """
                MATCH (c:Chunk)
                WHERE toLower(c.content) CONTAINS toLower($query)
                RETURN c.id as chunk_id, c.content as content,
                       c.chunk_type as chunk_type, c.quality_score as quality_score
                ORDER BY c.quality_score DESC
                LIMIT $limit
                """
                params = {'query': query, 'limit': limit}
            
            result = self.graph.query(cypher_query, params)
            
            chunks = []
            for record in result:
                chunks.append({
                    'chunk_id': record['chunk_id'],
                    'content': record['content'],
                    'chunk_type': record['chunk_type'],
                    'quality_score': record['quality_score'],
                    'similarity_score': 0.8,  # Default for text search
                    'search_type': 'basic_text'
                })
            
            return chunks
                
        except Exception as e:
            logger.error(f"Basic text search failed: {e}")
            return []
    
    async def get_chunk_statistics(self, document_id: str) -> Dict[str, Any]:
        """Get comprehensive statistics about chunks for a document."""
        try:
            query = """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
            RETURN 
                count(c) as total_chunks,
                avg(c.size) as avg_chunk_size,
                min(c.size) as min_chunk_size,
                max(c.size) as max_chunk_size,
                avg(c.quality_score) as avg_quality_score,
                sum(case when c.has_overlap then 1 else 0 end) as chunks_with_overlap,
                collect(distinct c.chunk_type) as chunk_types,
                sum(case when c.embedding_ready then 1 else 0 end) as embedding_ready_chunks
            """
            
            result = self.graph.query(query, {'document_id': document_id})
            record = result[0] if result else None
            
            if record:
                return {
                    'total_chunks': record['total_chunks'],
                    'avg_chunk_size': record['avg_chunk_size'],
                    'min_chunk_size': record['min_chunk_size'],
                    'max_chunk_size': record['max_chunk_size'],
                    'avg_quality_score': record['avg_quality_score'],
                    'chunks_with_overlap': record['chunks_with_overlap'],
                    'chunk_types': record['chunk_types'],
                    'embedding_ready_chunks': record['embedding_ready_chunks'],
                    'embedding_coverage': record['embedding_ready_chunks'] / max(record['total_chunks'], 1)
                }
            else:
                return {'error': 'No chunks found for document'}
                    
        except Exception as e:
            logger.error(f"Failed to get chunk statistics for document {document_id}: {e}")
            return {'error': str(e)}
    
    async def delete_chunks(self, document_id: str) -> Dict[str, Any]:
        """Delete all chunks for a document including embeddings."""
        try:
            query = """
            MATCH (d:Document {id: $document_id})-[:HAS_CHUNK]->(c:Chunk)
            DETACH DELETE c
            """
            
            self.graph.query(query, {'document_id': document_id})
            
            return {
                'success': True,
                'message': f'Successfully deleted chunks for document {document_id}'
            }
                
        except Exception as e:
            logger.error(f"Failed to delete chunks for document {document_id}: {e}")
            return {
                'success': False,
                'error': str(e),
                'message': f'Failed to delete chunks for document {document_id}'
            }


# Backward compatibility class
class ChunkStorageService(ChunkingStorageService):
    """Backward compatibility wrapper."""
    
    def store_chunks(self, contract_id: str, chunks: List, tenant_id: str = "default-tenant") -> List[str]:
        """Synchronous backward compatibility method handling both objects and dictionaries."""
        chunk_ids = []
        
        def safe_get(chunk_item: Any, attr: str, default: Any = None) -> Any:
            """Safely extract from dict or object following DRY principles."""
            if isinstance(chunk_item, dict):
                return chunk_item.get(attr, default)
            return getattr(chunk_item, attr, default)
            
        for i, chunk in enumerate(chunks):
            chunk_id = f"{contract_id}_chunk_{i}"
            
            try:
                # Extract properties safely regardless of input type
                content = safe_get(chunk, 'content', '')
                chunk_type = safe_get(chunk, 'chunk_type', safe_get(chunk, 'type', 'sentence'))
                confidence = safe_get(chunk, 'confidence', safe_get(chunk, 'quality_score', 1.0))
                
                self.graph.query("""
                    MERGE (dc:DocumentChunk {chunk_id: $chunk_id})
                    SET dc.contract_id = $contract_id,
                        dc.tenant_id = $tenant_id,
                        dc.chunk_order = $order,
                        dc.chunk_size = $size,
                        dc.chunk_type = $type,
                        dc.content = $content,
                        dc.confidence = $confidence,
                        dc.created_at = datetime()
                    
                    WITH dc
                    MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id})
                    MERGE (c)-[:CONTAINS_CHUNK]->(dc)
                """, {
                    "chunk_id": chunk_id,
                    "contract_id": contract_id,
                    "tenant_id": tenant_id,
                    "order": i,
                    "size": len(content),
                    "type": chunk_type,
                    "content": content,
                    "confidence": float(confidence)
                })
                
                chunk_ids.append(chunk_id)
                
            except Exception as e:
                logger.error(f"Failed to store chunk {chunk_id}: {e}", exc_info=True)
        
        return chunk_ids
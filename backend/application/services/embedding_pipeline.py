"""Multi-level embedding pipeline shared by the upload services."""
from backend.agents.agent_workflow_tracker import workflow_tracker
from backend.embeddings.orchestrator import EmbeddingOrchestrator
from backend.embeddings.validator import EmbeddingValidator
from backend.shared.utils.contract_search_tool import graph as shared_graph
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)


class EmbeddingPipeline:
    """Generate document/section/clause/relationship embeddings and store them."""

    def __init__(self, graph=None):
        self.graph = graph or shared_graph
        self.embedding_orchestrator = EmbeddingOrchestrator()
        self.embedding_validator = EmbeddingValidator()

    def run(self, contract_id: str, extracted_text: str, filename: str = "", tenant_id: str = "default-tenant") -> bool:
        """Blocking; call from a worker thread or background task."""
        self.tenant_id = tenant_id
        return self._process_enhanced_embeddings(contract_id, extracted_text, filename)

    def _process_enhanced_embeddings(self, contract_id: str, extracted_text: str, filename: str) -> bool:
        """Process multi-level embeddings for uploaded contract"""
        
        # Track embedding processing
        embedding_execution = workflow_tracker.start_agent(
            "Enhanced Embedding Agent",
            "Generate multi-level embeddings (document, section, clause, relationship)",
            f"Contract ID: {contract_id}"
        )
        
        try:
            logger.info(f"Processing enhanced embeddings for contract: {contract_id}")
            
            if not extracted_text or len(extracted_text.strip()) < 50:
                workflow_tracker.error_agent(embedding_execution, "Insufficient text for embedding processing")
                return False
            
            # Process with orchestrator
            processing_result = self.embedding_orchestrator.process_document(
                content=extracted_text,
                metadata={"file_id": contract_id, "source": "upload", "filename": filename}
            )
            
            # Validate results
            all_embeddings = (
                processing_result.document_embeddings + 
                processing_result.clause_embeddings + 
                processing_result.relationship_embeddings
            )
            
            if not all_embeddings:
                workflow_tracker.error_agent(embedding_execution, "No embeddings generated")
                return False
            
            validation_result = self.embedding_validator.validate_embeddings(all_embeddings)
            
            if not validation_result.is_valid:
                workflow_tracker.error_agent(embedding_execution, f"Validation failed: {validation_result.errors}")
                return False
            
            # Store embeddings in Neo4j
            self._store_enhanced_embeddings(contract_id, processing_result)
            
            workflow_tracker.complete_agent(
                embedding_execution, 
                f"Generated {len(all_embeddings)} embeddings: {len(processing_result.document_embeddings)} doc, {len(processing_result.clause_embeddings)} clause, {len(processing_result.relationship_embeddings)} relationship"
            )
            
            logger.info(f"Enhanced embeddings processed successfully for contract: {contract_id}")
            return True
            
        except Exception as e:
            workflow_tracker.error_agent(embedding_execution, f"Embedding processing failed: {str(e)}")
            logger.error(f"Enhanced embedding processing failed for {contract_id}: {e}")
            return False
    
    def _store_enhanced_embeddings(self, contract_id: str, processing_result):
        """Store enhanced embeddings in Neo4j"""
        
        # Store document embeddings
        for doc_embedding in processing_result.document_embeddings:
            if doc_embedding.metadata.get("level") == "document":
                self.graph.query("""
                    MATCH (c:Contract {file_id: $file_id, tenant_id: $tenant_id})
                    SET c.document_embedding = $embedding,
                        c.summary_embedding = $embedding
                """, {
                    "file_id": contract_id,
                    "tenant_id": self.tenant_id,
                    "embedding": doc_embedding.embedding
                })
            
            elif doc_embedding.metadata.get("level") == "section":
                section_id = f"{contract_id}_section_{doc_embedding.metadata.get('section_index', 0)}"
                self.graph.query("""
                    MATCH (c:Contract {file_id: $file_id, tenant_id: $tenant_id})
                    MERGE (s:Section {id: $section_id})
                    SET s.tenant_id = $tenant_id,
                        s.section_type = $section_type,
                        s.content = $content,
                        s.embedding = $embedding,
                        s.order = $order
                    MERGE (c)-[:HAS_SECTION]->(s)
                """, {
                    "file_id": contract_id,
                    "section_id": section_id,
                    "tenant_id": self.tenant_id,
                    "section_type": doc_embedding.metadata.get("section_type", "general"),
                    "content": doc_embedding.content,
                    "embedding": doc_embedding.embedding,
                    "order": doc_embedding.metadata.get("section_index", 0)
                })
        
        # Store clause embeddings
        for clause_embedding in processing_result.clause_embeddings:
            clause_id = f"{contract_id}_clause_{clause_embedding.metadata.get('start_position', 0)}"
            self.graph.query("""
                MATCH (c:Contract {file_id: $file_id, tenant_id: $tenant_id})
                MERGE (cl:Clause {id: $clause_id})
                SET cl.tenant_id = $tenant_id,
                    cl.clause_type = $clause_type,
                    cl.content = $content,
                    cl.embedding = $embedding,
                    cl.confidence = $confidence,
                    cl.start_position = $start_position,
                    cl.end_position = $end_position
                MERGE (c)-[:CONTAINS_CLAUSE]->(cl)
            """, {
                "file_id": contract_id,
                "clause_id": clause_id,
                "tenant_id": self.tenant_id,
                "clause_type": clause_embedding.metadata.get("clause_type", "unknown"),
                "content": clause_embedding.content,
                "embedding": clause_embedding.embedding,
                "confidence": clause_embedding.metadata.get("confidence", 0.0),
                "start_position": clause_embedding.metadata.get("start_position", 0),
                "end_position": clause_embedding.metadata.get("end_position", 0)
            })
        
        # Store relationship embeddings
        for rel_embedding in processing_result.relationship_embeddings:
            if rel_embedding.metadata.get("relationship_type") == "PARTY_TO":
                party_name = rel_embedding.metadata.get("party_name", "")
                if party_name:
                    self.graph.query("""
                        MATCH (c:Contract {file_id: $file_id, tenant_id: $tenant_id})
                        MATCH (c)<-[r:PARTY_TO]-(p:Party {name: $party_name})
                        SET r.embedding = $embedding,
                            r.context = $context
                    """, {
                        "file_id": contract_id,
                        "tenant_id": self.tenant_id,
                        "party_name": party_name,
                        "embedding": rel_embedding.embedding,
                        "context": rel_embedding.content
                    })
    

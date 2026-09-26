"""
Enterprise Database Schema Migration
Implements missing enterprise features from design documents
"""

import sys
import os

# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.infrastructure.contract_repository import Neo4jContractRepository
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

class EnterpriseSchemaMigration:
    """Enterprise database schema migration"""
    
    def __init__(self):
        self.repository = Neo4jContractRepository()
    
    def migrate_enterprise_schema(self):
        """Apply enterprise schema changes"""
        try:
            self._add_multi_tenancy()
            self._add_document_versioning()
            self._add_chunking_storage()
            self._add_embeddings_storage()
            self._add_processing_lineage()
            self._add_analysis_storage()
            self._create_enterprise_indexes()
            logger.info("Enterprise schema migration completed successfully")
        except Exception as e:
            logger.error(f"Enterprise schema migration failed: {e}")
            raise
    
    def _add_multi_tenancy(self):
        """Add multi-tenant support"""
        queries = [
            # Add tenant nodes and relationships
            """
            MERGE (t:Tenant {tenant_id: 'default-tenant'})
            SET t.name = 'Demo Law Firm',
                t.created_at = datetime(),
                t.status = 'active'
            """,
            
            """
            MERGE (t:Tenant {tenant_id: 'demo_tenant_2'})
            SET t.name = 'Demo Corporate Legal',
                t.created_at = datetime(),
                t.status = 'active'
            """,
            
            # Add tenant_id to existing contracts
            """
            MATCH (c:Contract)
            WHERE c.tenant_id IS NULL
            SET c.tenant_id = 'default-tenant'
            """,
            
            # Create tenant constraint
            "CREATE CONSTRAINT tenant_id_unique IF NOT EXISTS FOR (t:Tenant) REQUIRE t.tenant_id IS UNIQUE"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                logger.info(f"Multi-tenancy: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Query failed (may already exist): {e}")
    
    def _add_document_versioning(self):
        """Add document versioning system"""
        queries = [
            # Create ContractVersion nodes
            """
            MERGE (cv:ContractVersion {version_id: 'sample_version'})
            SET cv.contract_id = 'sample_contract',
                cv.tenant_id = 'default-tenant',
                cv.version_number = 1,
                cv.changes_summary = 'Initial version',
                cv.created_at = datetime(),
                cv.created_by = 'system'
            """,
            
            # Add version tracking to contracts
            """
            MATCH (c:Contract)
            WHERE c.version_number IS NULL
            SET c.version_number = 1,
                c.is_current_version = true
            """,
            
            # Create version relationships
            """
            MATCH (c:Contract), (cv:ContractVersion)
            WHERE c.file_id = cv.contract_id
            MERGE (c)-[:HAS_VERSION]->(cv)
            """,
            
            "CREATE INDEX contract_version_number IF NOT EXISTS FOR (cv:ContractVersion) ON (cv.version_number)",
            "CREATE INDEX contract_version_tenant IF NOT EXISTS FOR (cv:ContractVersion) ON (cv.tenant_id)"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                logger.info(f"Versioning: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Query failed (may already exist): {e}")
    
    def _add_chunking_storage(self):
        """Add document chunking storage"""
        queries = [
            # Create DocumentChunk nodes
            """
            MERGE (dc:DocumentChunk {chunk_id: 'sample_chunk'})
            SET dc.contract_id = 'sample_contract',
                dc.tenant_id = 'default-tenant',
                dc.chunk_order = 1,
                dc.chunk_size = 1024,
                dc.chunk_type = 'paragraph',
                dc.content = 'Sample chunk content',
                dc.page_range = [1, 1],
                dc.created_at = datetime()
            """,
            
            # Create chunk relationships
            """
            MATCH (c:Contract), (dc:DocumentChunk)
            WHERE c.file_id = dc.contract_id
            MERGE (c)-[:CONTAINS_CHUNK]->(dc)
            """,
            
            "CREATE INDEX chunk_contract_tenant IF NOT EXISTS FOR (dc:DocumentChunk) ON (dc.contract_id, dc.tenant_id)",
            "CREATE INDEX chunk_order IF NOT EXISTS FOR (dc:DocumentChunk) ON (dc.chunk_order)"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                logger.info(f"Chunking: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Query failed (may already exist): {e}")
    
    def _add_embeddings_storage(self):
        """Add vector embeddings storage"""
        queries = [
            # Create DocumentEmbedding nodes
            """
            MERGE (de:DocumentEmbedding {embedding_id: 'sample_embedding'})
            SET de.chunk_id = 'sample_chunk',
                de.tenant_id = 'default-tenant',
                de.model_name = 'gemini-embedding-001',
                de.vector_dimensions = 1536,
                de.created_at = datetime()
            """,
            
            # Create embedding relationships
            """
            MATCH (dc:DocumentChunk), (de:DocumentEmbedding)
            WHERE dc.chunk_id = de.chunk_id
            MERGE (dc)-[:HAS_EMBEDDING]->(de)
            """,
            
            "CREATE INDEX embedding_chunk_tenant IF NOT EXISTS FOR (de:DocumentEmbedding) ON (de.chunk_id, de.tenant_id)",
            "CREATE INDEX embedding_model IF NOT EXISTS FOR (de:DocumentEmbedding) ON (de.model_name)"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                logger.info(f"Embeddings: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Query failed (may already exist): {e}")
    
    def _add_processing_lineage(self):
        """Add processing lineage tracking"""
        queries = [
            # Create ProcessingLineage nodes
            """
            MERGE (pl:ProcessingLineage {lineage_id: 'sample_lineage'})
            SET pl.contract_id = 'sample_contract',
                pl.tenant_id = 'default-tenant',
                pl.processing_step = 'chunk',
                pl.input_data_id = 'contract_upload',
                pl.output_data_id = 'document_chunks',
                pl.model_version = 'chunker_v1.0',
                pl.confidence_score = 0.95,
                pl.processed_at = datetime(),
                pl.processed_by = 'system'
            """,
            
            # Create lineage relationships
            """
            MATCH (c:Contract), (pl:ProcessingLineage)
            WHERE c.file_id = pl.contract_id
            MERGE (c)-[:HAS_LINEAGE]->(pl)
            """,
            
            "CREATE INDEX lineage_contract_step IF NOT EXISTS FOR (pl:ProcessingLineage) ON (pl.contract_id, pl.processing_step)",
            "CREATE INDEX lineage_tenant IF NOT EXISTS FOR (pl:ProcessingLineage) ON (pl.tenant_id)"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                logger.info(f"Lineage: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Query failed (may already exist): {e}")
    
    def _add_analysis_storage(self):
        """Add contract analysis storage"""
        queries = [
            # Create ContractAnalysis nodes
            """
            MERGE (ca:ContractAnalysis {analysis_id: 'sample_analysis'})
            SET ca.contract_id = 'sample_contract',
                ca.tenant_id = 'default-tenant',
                ca.analysis_type = 'clause_extraction',
                ca.results = '{"clauses": [], "confidence": 0.9}',
                ca.confidence_score = 0.9,
                ca.model_version = 'cuad_v1.0',
                ca.created_at = datetime()
            """,
            
            # Create analysis relationships
            """
            MATCH (c:Contract), (ca:ContractAnalysis)
            WHERE c.file_id = ca.contract_id
            MERGE (c)-[:HAS_ANALYSIS]->(ca)
            """,
            
            "CREATE INDEX analysis_contract_type IF NOT EXISTS FOR (ca:ContractAnalysis) ON (ca.contract_id, ca.analysis_type)",
            "CREATE INDEX analysis_tenant IF NOT EXISTS FOR (ca:ContractAnalysis) ON (ca.tenant_id)"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                logger.info(f"Analysis: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Query failed (may already exist): {e}")
    
    def _create_enterprise_indexes(self):
        """Create enterprise performance indexes"""
        queries = [
            # Multi-tenant indexes
            "CREATE INDEX contract_tenant_date IF NOT EXISTS FOR (c:Contract) ON (c.tenant_id, c.created_at)",
            "CREATE INDEX contract_tenant_status IF NOT EXISTS FOR (c:Contract) ON (c.tenant_id, c.processing_status)",
            
            # Version tracking indexes
            "CREATE INDEX contract_version_current IF NOT EXISTS FOR (c:Contract) ON (c.is_current_version)",
            
            # Performance indexes for common queries
            "CREATE INDEX chunk_tenant_contract IF NOT EXISTS FOR (dc:DocumentChunk) ON (dc.tenant_id, dc.contract_id)",
            "CREATE INDEX embedding_tenant_model IF NOT EXISTS FOR (de:DocumentEmbedding) ON (de.tenant_id, de.model_name)",
            "CREATE INDEX lineage_tenant_step IF NOT EXISTS FOR (pl:ProcessingLineage) ON (pl.tenant_id, pl.processing_step)",
            "CREATE INDEX analysis_tenant_type IF NOT EXISTS FOR (ca:ContractAnalysis) ON (ca.tenant_id, ca.analysis_type)"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                logger.info(f"Index: {query[:50]}...")
            except Exception as e:
                logger.warning(f"Query failed (may already exist): {e}")
    
    def verify_enterprise_migration(self) -> bool:
        """Verify enterprise migration was successful"""
        try:
            # Check if enterprise nodes exist
            result = self.repository.graph.query("""
                MATCH (t:Tenant)
                OPTIONAL MATCH (cv:ContractVersion)
                OPTIONAL MATCH (dc:DocumentChunk)
                OPTIONAL MATCH (de:DocumentEmbedding)
                OPTIONAL MATCH (pl:ProcessingLineage)
                OPTIONAL MATCH (ca:ContractAnalysis)
                RETURN 
                    count(t) as tenants,
                    count(cv) as versions,
                    count(dc) as chunks,
                    count(de) as embeddings,
                    count(pl) as lineage,
                    count(ca) as analysis
            """)
            
            if result and len(result) > 0:
                counts = result[0]
                logger.info(f"Enterprise migration verification:")
                logger.info(f"  - Tenants: {counts.get('tenants', 0)}")
                logger.info(f"  - Versions: {counts.get('versions', 0)}")
                logger.info(f"  - Chunks: {counts.get('chunks', 0)}")
                logger.info(f"  - Embeddings: {counts.get('embeddings', 0)}")
                logger.info(f"  - Lineage: {counts.get('lineage', 0)}")
                logger.info(f"  - Analysis: {counts.get('analysis', 0)}")
                
                return all(counts.get(key, 0) > 0 for key in ['tenants', 'versions', 'chunks', 'embeddings', 'lineage', 'analysis'])
            
            return False
            
        except Exception as e:
            logger.error(f"Enterprise migration verification failed: {e}")
            return False

def run_enterprise_migration():
    """Run the enterprise schema migration"""
    migration = EnterpriseSchemaMigration()
    migration.migrate_enterprise_schema()
    
    if migration.verify_enterprise_migration():
        print("✅ Enterprise schema migration completed successfully")
    else:
        print("❌ Enterprise schema migration verification failed")

if __name__ == "__main__":
    run_enterprise_migration()
from backend.domain.entities import IContractRepository
from backend.shared.utils.contract_search_tool import graph, embedding
from backend.shared.utils.utils import parse_date_to_iso
from typing import Dict, Any, Optional
import asyncio
import uuid
from datetime import datetime
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

def _to_float(value) -> Optional[float]:
    """LLMs return amounts as numbers or strings like '$1,200,000.00'."""
    if value is None or isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


class Neo4jContractRepository(IContractRepository):
    """Repository implementation using existing Neo4j infrastructure - DRY principle"""
    
    def __init__(self):
        self.graph = graph  # Reuse existing connection
        self.embedding_service = embedding  # Reuse existing embedding service
    
    async def get_contract_by_id(self, contract_id: str, tenant_id: str = "default-tenant") -> Dict[str, Any]:
        """Get contract data by ID - Enforces multi-tenant isolation"""
        return await asyncio.to_thread(self.get_contract_by_id_sync, contract_id, tenant_id)

    def get_contract_by_id_sync(self, contract_id: str, tenant_id: str = "default-tenant") -> Dict[str, Any]:
        """Blocking implementation of get_contract_by_id (runs on a worker thread)."""
        try:
            query = """
            MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id})
            OPTIONAL MATCH (c)<-[r:PARTY_TO]-(p:Party)
            RETURN c.file_id as file_id,
                   c.contract_type as contract_type,
                   c.summary as summary,
                   c.contract_scope as contract_scope,
                   c.full_text as full_text,
                   c.effective_date as effective_date,
                   c.end_date as end_date,
                   c.total_amount as total_amount,
                   collect({name: p.name, role: r.role}) as parties
            """
            
            result = self.graph.query(query, {"contract_id": contract_id, "tenant_id": tenant_id})
            
            if result:
                contract_data = result[0]
                return {
                    "file_id": contract_data["file_id"],
                    "contract_type": contract_data["contract_type"],
                    "summary": contract_data["summary"] or "",
                    "contract_scope": contract_data["contract_scope"] or "",
                    "full_text": contract_data["full_text"] or "",
                    "effective_date": str(contract_data["effective_date"]) if contract_data["effective_date"] else None,
                    "end_date": str(contract_data["end_date"]) if contract_data["end_date"] else None,
                    "total_amount": contract_data["total_amount"],
                    "parties": [p for p in contract_data["parties"] if p["name"]]
                }
            else:
                return None
                
        except Exception as e:
            logger.error(f"Failed to get contract {contract_id}: {e}")
            return None
    
    def find_duplicate(self, tenant_id: str, content_hash: str) -> Optional[str]:
        """Return the id of an existing contract with identical content for this tenant."""
        if not content_hash:
            return None
        rows = self.graph.query(
            "MATCH (c:Contract {tenant_id: $tenant_id, content_hash: $content_hash}) "
            "RETURN c.file_id AS file_id LIMIT 1",
            {"tenant_id": tenant_id, "content_hash": content_hash},
        )
        return rows[0]["file_id"] if rows else None

    async def store_contract(self, contract_data: Dict[str, Any], tenant_id: str = "default-tenant") -> str:
        """Store contract in Neo4j with tenant isolation"""
        return await asyncio.to_thread(self.store_contract_sync, contract_data, tenant_id)

    def store_contract_sync(self, contract_data: Dict[str, Any], tenant_id: str = "default-tenant") -> str:
        """Blocking implementation of store_contract (runs on a worker thread)."""
        try:
            # Generate unique contract ID
            contract_id = f"UPLOADED_{uuid.uuid4().hex[:8].upper()}_{datetime.now().strftime('%Y%m%d')}"
            
            # Log what we're about to store
            logger.info(f"=== STORING CONTRACT ===")
            logger.info(f"Contract ID: {contract_id}")
            logger.info(f"Contract Type: {contract_data.get('contract_type', 'Unknown')}")
            logger.info(f"Summary: {contract_data.get('summary', '')[:100]}...")
            logger.info(f"Is Contract: {contract_data.get('is_contract', False)}")
            logger.info(f"Confidence: {contract_data.get('confidence_score', 0.0)}")
            
            # Generate embedding for the contract summary
            summary_text = contract_data.get("summary", "")
            contract_embedding = []
            
            if summary_text:
                try:
                    contract_embedding = self.embedding_service.embed_query(summary_text)
                    logger.info(f"Generated embedding with {len(contract_embedding)} dimensions")
                except Exception as e:
                    logger.warning(f"Failed to generate embedding: {e}")
            
            contract_query = """
            CREATE (c:Contract {
                file_id: $file_id,
                tenant_id: $tenant_id,
                summary: $summary,
                contract_type: $contract_type,
                contract_scope: $contract_scope,
                full_text: $full_text,
                effective_date: CASE WHEN $effective_date IS NOT NULL THEN date($effective_date) ELSE NULL END,
                end_date: CASE WHEN $end_date IS NOT NULL THEN date($end_date) ELSE NULL END,
                total_amount: $total_amount,
                embedding: $embedding,
                original_filename: $original_filename,
                content_hash: $content_hash,
                upload_date: datetime(),
                source: 'PDF_UPLOAD'
            })
            RETURN c.file_id as contract_id
            """
            
            contract_params = {
                "file_id": contract_id,
                "tenant_id": tenant_id,
                "summary": contract_data.get("summary", ""),
                "contract_type": contract_data.get("contract_type", "Unknown"),
                "contract_scope": ", ".join(contract_data.get("key_terms", [])),
                "full_text": contract_data.get("full_text", ""),
                "effective_date": parse_date_to_iso(contract_data.get("effective_date")),
                "end_date": parse_date_to_iso(contract_data.get("end_date")),
                "total_amount": _to_float(contract_data.get("total_amount")),
                "embedding": contract_embedding,
                "original_filename": contract_data.get("filename"),
                "content_hash": contract_data.get("content_hash"),
            }
            
            logger.info(f"Executing Neo4j query with params: {list(contract_params.keys())}")
            
            # Execute contract creation
            result = self.graph.query(contract_query, contract_params)
            
            if not result:
                raise Exception("Failed to create contract node")
            
            created_contract_id = result[0]["contract_id"]
            logger.info(f"Contract node created successfully: {created_contract_id}")
            
            # Create party relationships
            parties = contract_data.get("parties", [])
            logger.info(f"Creating {len(parties)} party relationships")
            self._create_party_relationships(created_contract_id, tenant_id, parties)
            
            # Create governing law relationship
            governing_law = contract_data.get("governing_law")
            if governing_law:
                logger.info(f"Creating governing law relationship: {governing_law}")
                self._create_governing_law_relationship(created_contract_id, tenant_id, governing_law)
            
            logger.info(f"=== CONTRACT STORED SUCCESSFULLY: {created_contract_id} ===")
            return created_contract_id
            
        except Exception as e:
            logger.error(f"Failed to store contract: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise
    
    def _create_party_relationships(self, contract_id: str, tenant_id: str, parties: list):
        """Create party nodes and relationships with tenant context"""
        
        for party_data in parties:
            if not party_data.get("name"):
                continue
                
            party_query = """
            MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id})
            MERGE (p:Party {name: $party_name, tenant_id: $tenant_id})
            MERGE (p)-[:PARTY_TO {role: $role}]->(c)
            """
            
            party_params = {
                "contract_id": contract_id,
                "tenant_id": tenant_id,
                "party_name": party_data["name"],
                "role": party_data.get("role", "Unknown")
            }
            
            self.graph.query(party_query, party_params)
            logger.info(f"Created party relationship: {party_data['name']}")
    
    def _create_governing_law_relationship(self, contract_id: str, tenant_id: str, governing_law: str):
        """Create governing law relationship with tenant context"""
        
        gov_law_query = """
        MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id})
        MERGE (country:Country {name: $country_name})
        MERGE (c)-[:HAS_GOVERNING_LAW]->(country)
        """
        
        gov_law_params = {
            "contract_id": contract_id,
            "tenant_id": tenant_id,
            "country_name": governing_law
        }
        
        self.graph.query(gov_law_query, gov_law_params)
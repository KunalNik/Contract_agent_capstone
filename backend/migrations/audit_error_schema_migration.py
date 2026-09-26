"""
Audit and Error Tracking Schema Migration
Creates AuditLog and ErrorLog nodes with indexes
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.infrastructure.contract_repository import Neo4jContractRepository
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

class AuditErrorSchemaMigration:
    """Migration for audit and error tracking schema"""
    
    def __init__(self):
        self.repository = Neo4jContractRepository()
    
    def migrate(self):
        """Apply audit and error schema migration"""
        try:
            self._create_audit_indexes()
            self._create_error_indexes()
            self._create_sample_data()
            logger.info("Audit and error schema migration completed")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            raise
    
    def _create_audit_indexes(self):
        """Create indexes for AuditLog nodes"""
        queries = [
            "CREATE INDEX audit_resource_id IF NOT EXISTS FOR (a:AuditLog) ON (a.resource_id)",
            "CREATE INDEX audit_timestamp IF NOT EXISTS FOR (a:AuditLog) ON (a.timestamp)",
            "CREATE INDEX audit_tenant_id IF NOT EXISTS FOR (a:AuditLog) ON (a.tenant_id)",
            "CREATE INDEX audit_event_type IF NOT EXISTS FOR (a:AuditLog) ON (a.event_type)",
            "CREATE INDEX audit_user_id IF NOT EXISTS FOR (a:AuditLog) ON (a.user_id)"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                print(f"✅ Created audit index: {query.split('FOR')[0].split('INDEX')[1].strip()}")
            except Exception as e:
                print(f"⚠️ Index may already exist: {e}")
    
    def _create_error_indexes(self):
        """Create indexes for ErrorLog nodes"""
        queries = [
            "CREATE INDEX error_timestamp IF NOT EXISTS FOR (e:ErrorLog) ON (e.timestamp)",
            "CREATE INDEX error_category IF NOT EXISTS FOR (e:ErrorLog) ON (e.category)",
            "CREATE INDEX error_severity IF NOT EXISTS FOR (e:ErrorLog) ON (e.severity)",
            "CREATE INDEX error_tenant_id IF NOT EXISTS FOR (e:ErrorLog) ON (e.tenant_id)",
            "CREATE INDEX error_resource_id IF NOT EXISTS FOR (e:ErrorLog) ON (e.resource_id)"
        ]
        
        for query in queries:
            try:
                self.repository.graph.query(query)
                print(f"✅ Created error index: {query.split('FOR')[0].split('INDEX')[1].strip()}")
            except Exception as e:
                print(f"⚠️ Index may already exist: {e}")
    
    def _create_sample_data(self):
        """Create sample audit and error data for testing"""
        # Sample audit log
        audit_query = """
        MERGE (a:AuditLog {audit_id: 'sample_audit_001'})
        SET a.event_type = 'document_upload',
            a.resource_id = 'sample_contract',
            a.action = 'upload_completed',
            a.user_id = 'system',
            a.tenant_id = 'default-tenant',
            a.status = 'success',
            a.timestamp = datetime(),
            a.metadata = '{"test": "migration"}',
            a.error_details = null
        """
        
        # Sample error log
        error_query = """
        MERGE (e:ErrorLog {error_id: 'sample_error_001'})
        SET e.error_type = 'ValidationError',
            e.error_message = 'Sample validation error for testing',
            e.category = 'validation_error',
            e.severity = 'medium',
            e.operation = 'document_validation',
            e.resource_id = 'sample_contract',
            e.user_id = 'system',
            e.tenant_id = 'default-tenant',
            e.timestamp = datetime(),
            e.stack_trace = 'Sample stack trace',
            e.metadata = '{"test": "migration"}',
            e.recovery_action = null
        """
        
        try:
            self.repository.graph.query(audit_query)
            print("✅ Created sample AuditLog node")
            
            self.repository.graph.query(error_query)
            print("✅ Created sample ErrorLog node")
        except Exception as e:
            print(f"⚠️ Sample data creation failed: {e}")
    
    def verify_migration(self):
        """Verify migration was successful"""
        try:
            # Check audit logs
            audit_result = self.repository.graph.query("MATCH (a:AuditLog) RETURN count(a) as count")
            audit_count = audit_result[0]["count"] if audit_result else 0
            
            # Check error logs
            error_result = self.repository.graph.query("MATCH (e:ErrorLog) RETURN count(e) as count")
            error_count = error_result[0]["count"] if error_result else 0
            
            print(f"✅ Migration verification:")
            print(f"   - AuditLog nodes: {audit_count}")
            print(f"   - ErrorLog nodes: {error_count}")
            
            return audit_count > 0 and error_count > 0
            
        except Exception as e:
            print(f"❌ Migration verification failed: {e}")
            return False

def run_migration():
    """Run the audit and error schema migration"""
    migration = AuditErrorSchemaMigration()
    migration.migrate()
    
    if migration.verify_migration():
        print("✅ Audit and error schema migration completed successfully")
    else:
        print("❌ Migration verification failed")

if __name__ == "__main__":
    run_migration()
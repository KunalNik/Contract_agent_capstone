"""Policy caching service with working per-tenant invalidation."""

from typing import List, Dict, Any, Optional

from backend.shared.cache.redis_cache import cache, cache_enabled


class PolicyCacheService:
    """Caches policy lookups per tenant.

    Every key includes a per-tenant generation number; invalidating a tenant
    bumps the generation so stale entries are never read again. (The previous
    invalidate method was a no-op, so newly uploaded policies stayed invisible
    until the TTL expired, and keys included the service object's address so
    nothing was ever reused.)
    """

    TTL_RULES = 3600
    TTL_SEARCH = 1800
    TTL_DOCUMENT = 7200

    def _generation(self, tenant_id: str) -> str:
        value = cache.redis_client.get(f"policy_gen:{tenant_id}") if cache_enabled() else None
        return str(value or 0)

    def _cached(self, prefix: str, tenant_id: str, ttl: int, loader, *key_parts):
        if not cache_enabled():
            return loader()
        key = cache.generate_key(prefix, tenant_id, self._generation(tenant_id), *key_parts)
        hit = cache.get(key)
        if hit is not None:
            return hit
        value = loader()
        if value is not None:
            cache.set(key, value, ttl)
        return value

    def get_cached_policies(self, tenant_id: str, contract_type: str) -> List[Dict[str, Any]]:
        """Applicable active rules for a tenant and contract type."""
        def load():
            from backend.infrastructure.policy_repository import PolicyRepository
            return [
                {
                    'id': policy.id,
                    'rule_text': policy.rule_text,
                    'rule_type': policy.rule_type,
                    'applies_to': policy.applies_to,
                    'severity': policy.severity,
                    'section_reference': policy.section_reference
                }
                for policy in PolicyRepository().get_applicable_policies(tenant_id, contract_type)
            ]
        return self._cached("policy_rules", tenant_id, self.TTL_RULES, load, contract_type)

    def get_cached_search_results(self, query: str, tenant_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Semantic search results."""
        def load():
            from backend.infrastructure.policy_repository import PolicyRepository
            return PolicyRepository().search_policies_semantic(query, tenant_id, limit)
        return self._cached("policy_search", tenant_id, self.TTL_SEARCH, load, query, limit)

    def get_cached_policy_document(self, policy_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
        """A single policy document (scoped to the tenant)."""
        def load():
            from backend.infrastructure.policy_repository import PolicyRepository
            policy = PolicyRepository().get_policy_by_id(policy_id, tenant_id=tenant_id)
            if not policy:
                return None
            return {
                'id': policy.id,
                'name': policy.name,
                'tenant_id': policy.tenant_id,
                'version': policy.version,
                'created_at': policy.created_at.isoformat() if policy.created_at else None,
                'checksum': policy.checksum,
                'rules': [
                    {
                        'id': rule.id,
                        'rule_text': rule.rule_text,
                        'rule_type': rule.rule_type,
                        'applies_to': rule.applies_to,
                        'severity': rule.severity,
                        'section_reference': rule.section_reference
                    }
                    for rule in policy.rules
                ]
            }
        return self._cached("policy_document", tenant_id, self.TTL_DOCUMENT, load, policy_id)

    def invalidate_policy_cache(self, tenant_id: str, policy_id: str = None):
        """Invalidate every cached policy entry for the tenant."""
        if cache_enabled():
            cache.incr(f"policy_gen:{tenant_id}")

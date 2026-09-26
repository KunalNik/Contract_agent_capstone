"""Policy workflow orchestrator: chunk the policy, then extract and store its rules."""

from typing import Dict, Any

from backend.agents.supervisor.interfaces import AgentContext, WorkflowContext
from backend.agents.supervisor.agent_registry import AgentRegistry
from backend.agents.policy_agents import PolicyChunkingAgent, PolicyExtractionAgent, PolicyComplianceAgent


class PolicyWorkflowOrchestrator:
    """Orchestrates policy workflows.

    (It used to construct ``SupervisorAgent()`` without its required
    arguments, so every policy upload failed before doing any work.)
    """

    def __init__(self):
        self.registry = AgentRegistry()
        self.registry.register_agent('policy_chunking', PolicyChunkingAgent())
        self.registry.register_agent('policy_extraction', PolicyExtractionAgent())
        self.registry.register_agent('policy_compliance', PolicyComplianceAgent())

    async def process_policy_document(self, policy_data: Dict[str, Any]) -> Dict[str, Any]:
        """Chunk the policy text, then extract, embed and store its rules."""
        workflow_context = WorkflowContext(
            workflow_id=f"policy_workflow_{policy_data.get('tenant_id', 'unknown')}",
            workflow_type="policy_processing",
            context_data={k: v for k, v in policy_data.items() if k != 'policy_text'}
        )

        results = []
        chunking = await self.registry.get_agent('policy_chunking').aexecute(AgentContext(
            input_data={
                'policy_text': policy_data['policy_text'],
                'tenant_id': policy_data['tenant_id'],
                'policy_name': policy_data.get('policy_name', 'Unknown Policy'),
            },
            workflow_context=workflow_context,
        ))
        results.append({'agent_id': 'policy_chunking', 'status': chunking.status,
                        'data': {k: v for k, v in chunking.data.items() if k != 'chunks'},
                        'confidence': chunking.confidence})
        final_result = chunking.data

        if chunking.status == 'success':
            extraction = await self.registry.get_agent('policy_extraction').aexecute(AgentContext(
                input_data={
                    'document_id': chunking.data['document_id'],
                    'tenant_id': policy_data['tenant_id'],
                    'chunks': chunking.data.get('chunks', []),
                    'policy_name': policy_data.get('policy_name', 'Untitled Policy'),
                    'version': policy_data.get('version', '1.0'),
                    'policy_type': policy_data.get('policy_type', 'compliance'),
                },
                workflow_context=workflow_context,
            ))
            results.append({'agent_id': 'policy_extraction', 'status': extraction.status,
                            'data': extraction.data, 'confidence': extraction.confidence})
            final_result = extraction.data

        return {
            'workflow_id': workflow_context.workflow_id,
            'status': 'success' if all(r['status'] == 'success' for r in results) else 'error',
            'steps': results,
            'final_result': final_result,
            'chunks_created': chunking.data.get('chunks_created', 0),
            'rules_extracted': final_result.get('rules_extracted', 0),
        }

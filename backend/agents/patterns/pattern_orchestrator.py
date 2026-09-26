"""Pattern Orchestrator - Coordinates AI patterns using existing supervisor infrastructure."""

from typing import Dict, Any, Optional, List
import logging

from backend.agents.patterns.react_agent import ReACTAgent
from backend.agents.patterns.chain_of_thought_agent import ChainOfThoughtAgent
from backend.agents.patterns.advanced_rag_agent import AdvancedRAGAgent
from backend.agents.supervisor.interfaces import IAgent, AgentContext, AgentResult

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)


class PatternOrchestrator(IAgent):
    """Orchestrates AI patterns based on task requirements using existing supervisor infrastructure."""
    
    def __init__(self):
        self.react_agent = ReACTAgent()
        self.cot_agent = ChainOfThoughtAgent()
        self.rag_agent = AdvancedRAGAgent()
    
    def execute(self, context: AgentContext) -> AgentResult:
        """Execute method required by IAgent interface."""
        from backend.shared.utils.async_utils import run_coro_sync
        result = run_coro_sync(self.process(context.input_data))
        return AgentResult(
            status='success' if result.get('success') else 'error',
            data=result,
            confidence=result.get('synthesized_result', {}).get('overall_confidence', 0.0)
        )
    
    def get_capabilities(self) -> List[str]:
        """Get capabilities method required by IAgent interface."""
        return ['react_pattern', 'chain_of_thought', 'advanced_rag', 'pattern_orchestration']
    
    async def process(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Process request using appropriate AI pattern combination."""
        try:
            task_type = context.get('task_type', 'analysis')
            use_patterns = context.get('patterns', ['react', 'cot', 'rag'])
            
            results = {}
            
            # Execute ReACT pattern if requested
            if 'react' in use_patterns:
                react_result = await self._execute_react_pattern(context)
                results['react'] = react_result
            
            # Execute Chain-of-Thought pattern if requested
            if 'cot' in use_patterns:
                cot_result = await self._execute_cot_pattern(context, results.get('react'))
                results['cot'] = cot_result
            
            # Execute Advanced RAG pattern if requested
            if 'rag' in use_patterns:
                rag_result = await self._execute_rag_pattern(context)
                results['rag'] = rag_result
            
            # Synthesize results
            final_result = await self._synthesize_results(results, context)
            
            succeeded = [name for name, r in results.items() if isinstance(r, dict) and r.get('success')]
            return {
                'success': bool(succeeded),
                'error': None if succeeded else '; '.join(
                    f"{name}: {r.get('error', 'failed')}" for name, r in results.items() if isinstance(r, dict)),
                'patterns_used': use_patterns,
                'patterns_succeeded': succeeded,
                'individual_results': results,
                'synthesized_result': final_result
            }
            
        except Exception as e:
            logger.error(f"Pattern orchestrator error: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    async def _execute_react_pattern(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute ReACT pattern for iterative analysis."""
        react_context = {
            'query': context.get('query', ''),
            'contract_text': context.get('contract_text', ''),
            'contract_id': context.get('contract_id') or 'unknown',
        }
        if context.get('max_iterations'):
            self.react_agent.max_iterations = int(context['max_iterations'])
        
        # BasePatternAgent exposes execute(); process() never existed
        return await self.react_agent.execute(react_context)
    
    async def _execute_cot_pattern(self, context: Dict[str, Any], 
                                 react_result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute Chain-of-Thought pattern for explicit reasoning."""
        cot_context = {
            'task_type': context.get('task_type', 'risk_assessment'),
            'clauses': context.get('clauses', []),
            'policies': context.get('policies', {}),
            'contract_text': context.get('contract_text', ''),
            'target_clause': context.get('target_clause') or context.get('query', ''),
            'contract_id': context.get('contract_id') or 'unknown',
        }
        
        # Incorporate ReACT findings if available
        if react_result and react_result.get('success'):
            findings = react_result.get('findings', [])
            cot_context['react_findings'] = findings
        
        return await self.cot_agent.execute(cot_context)
    
    async def _execute_rag_pattern(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Advanced RAG pattern for contextual analysis."""
        rag_context = {
            'query': context.get('query', ''),
            'contract_id': context.get('contract_id', '')
        }
        
        return await self.rag_agent.process(rag_context)
    
    async def _synthesize_results(self, results: Dict[str, Any], 
                                context: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesize results from multiple AI patterns."""
        synthesis = {
            'confidence_scores': {},
            'key_findings': [],
            'recommendations': [],
            'reasoning_trace': [],
            'contextual_insights': []
        }
        
        # Extract confidence scores
        if 'react' in results and results['react'].get('success'):
            synthesis['confidence_scores']['react'] = results['react'].get('final_confidence', 0.0)
        
        if 'cot' in results and results['cot'].get('success'):
            cot_result = results['cot'].get('final_result', {})
            synthesis['confidence_scores']['cot'] = cot_result.get('confidence', 0.0)
        
        if 'rag' in results and results['rag'].get('success'):
            rag_context = results['rag'].get('rag_context', {})
            synthesis['confidence_scores']['rag'] = rag_context.get('context_score', 0.0)
        
        # Extract key findings
        synthesis['key_findings'] = self._extract_key_findings(results)
        
        # Extract recommendations
        synthesis['recommendations'] = self._extract_recommendations(results)
        
        # Extract reasoning trace
        synthesis['reasoning_trace'] = self._extract_reasoning_trace(results)
        
        # Extract contextual insights
        synthesis['contextual_insights'] = self._extract_contextual_insights(results)
        
        # Calculate overall confidence
        confidences = list(synthesis['confidence_scores'].values())
        synthesis['overall_confidence'] = sum(confidences) / len(confidences) if confidences else 0.0
        
        return synthesis
    
    def _extract_key_findings(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract key findings from all patterns."""
        findings = []
        
        # ReACT findings
        if 'react' in results and results['react'].get('success'):
            react_findings = results['react'].get('findings', [])
            for finding in react_findings:
                findings.append({
                    'source': 'react',
                    'type': finding.get('type', 'unknown'),
                    'content': finding.get('content', ''),
                    'confidence': finding.get('relevance', 1.0)
                })
        
        # Chain-of-Thought findings
        if 'cot' in results and results['cot'].get('success'):
            cot_result = results['cot'].get('final_result', {})
            
            # Risk assessment findings
            violations = cot_result.get('violations', [])
            for violation in violations:
                findings.append({
                    'source': 'cot',
                    'type': 'policy_violation',
                    'content': violation.get('violation', ''),
                    'severity': violation.get('severity', 'UNKNOWN'),
                    'clause_type': violation.get('clause_type', '')
                })
            
            # Clause analysis findings
            extracted_clauses = cot_result.get('extracted_clauses', [])
            for clause in extracted_clauses:
                findings.append({
                    'source': 'cot',
                    'type': 'extracted_clause',
                    'content': clause.get('content', ''),
                    'key_terms': clause.get('key_terms', [])
                })
        
        return findings
    
    def _extract_recommendations(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract recommendations from all patterns."""
        recommendations = []
        
        # Chain-of-Thought recommendations
        if 'cot' in results and results['cot'].get('success'):
            cot_result = results['cot'].get('final_result', {})
            cot_recommendations = cot_result.get('recommendations', [])
            
            for rec in cot_recommendations:
                recommendations.append({
                    'source': 'cot',
                    'recommendation': rec.get('recommendation', ''),
                    'priority': rec.get('priority', 'MEDIUM'),
                    'clause_type': rec.get('clause_type', '')
                })
        
        # Advanced RAG recommendations
        if 'rag' in results and results['rag'].get('success'):
            rag_analysis = results['rag'].get('analysis', {})
            rag_recommendations = rag_analysis.get('recommendations', [])
            
            for rec in rag_recommendations:
                recommendations.append({
                    'source': 'rag',
                    'recommendation': rec.get('recommendation', ''),
                    'priority': rec.get('priority', 'MEDIUM'),
                    'type': rec.get('type', 'contextual'),
                    'confidence': rec.get('confidence', 0.0)
                })
        
        return recommendations
    
    def _extract_reasoning_trace(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract reasoning traces from Chain-of-Thought pattern."""
        trace = []
        
        if 'cot' in results and results['cot'].get('success'):
            thought_chain = results['cot'].get('thought_chain', [])
            
            for step in thought_chain:
                trace.append({
                    'step': step.get('step_number', 0),
                    'description': step.get('description', ''),
                    'reasoning': step.get('reasoning', ''),
                    'confidence': step.get('confidence', 0.0)
                })
        
        return trace
    
    def _extract_contextual_insights(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract contextual insights from Advanced RAG pattern."""
        insights = []
        
        if 'rag' in results and results['rag'].get('success'):
            rag_analysis = results['rag'].get('analysis', {})
            rag_insights = rag_analysis.get('insights', [])
            
            for insight in rag_insights:
                insights.append({
                    'type': insight.get('type', 'unknown'),
                    'insight': insight.get('insight', ''),
                    'confidence': insight.get('confidence', 0.0),
                    'data': insight.get('data', {})
                })
        
        return insights


# Factory for creating pattern orchestrator
class PatternOrchestratorFactory:
    """Factory for creating pattern orchestrator instances."""
    
    @staticmethod
    def create_orchestrator() -> PatternOrchestrator:
        """Create a new pattern orchestrator instance."""
        return PatternOrchestrator()
    
    @staticmethod
    def create_for_task(task_type: str) -> PatternOrchestrator:
        """Create orchestrator optimized for specific task type."""
        orchestrator = PatternOrchestrator()
        
        # Task-specific optimizations can be added here
        if task_type == 'clause_extraction':
            orchestrator.react_agent.max_iterations = 5  # More iterations for complex extraction
        elif task_type == 'risk_assessment':
            # Risk assessment benefits from all patterns
            pass
        
        return orchestrator
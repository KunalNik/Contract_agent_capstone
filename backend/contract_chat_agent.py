from backend.shared.utils.contract_search_tool import ContractSearchTool
from backend.shared.utils.enhanced_contract_search_tool import EnhancedContractSearchTool
from langchain_core.messages import SystemMessage
from langgraph.graph import START, MessagesState, StateGraph
# from langgraph.prebuilt import ToolNode, tools_condition
# Note: ToolNode import disabled to fix compatibility issues
# This file may need updates for newer LangGraph versions
from datetime import date


def get_agent(llm):
    # Define tools/llm
    tools = [ContractSearchTool(), EnhancedContractSearchTool()]
    llm_with_tools = llm.bind_tools(tools)

    # System message
    sys_msg = SystemMessage(
        content="You are a helpful assistant tasked with finding and explaining relevant information about internal contracts. "
        "Always explain results you get from the tools in a concise manner to not overwhelm the user but also don't be too technical. "
        "Answer questions as if you are answering to non-technical management level. "
        "Important: Be confident and accurate in your tool choice! Avoid asking follow-up questions if possible. "
        "Searches are automatically limited to the current user's organisation; never ask for a tenant ID. "
        f"Today is {date.today()}"
    )

    # Node
    def assistant(state: MessagesState):
        response = llm_with_tools.invoke([sys_msg] + state["messages"])
        
        # Log model decision
        from backend.infrastructure.agent_audit_service import AgentAuditService
        from backend.shared.utils.logger import correlation_id_var
        
        audit_service = AgentAuditService()
        session_id = correlation_id_var.get() or "unknown_session"
        
        # Log textual rationale if present
        if response.content:
            audit_service.log_model_decision(
                rationale=response.content[:500],
                session_id=session_id,
                metadata={"has_tool_calls": bool(response.tool_calls)}
            )
        elif response.tool_calls:
            audit_service.log_model_decision(
                rationale="Agent decided to call tools.",
                session_id=session_id,
                metadata={"tool_names": [tc['name'] for tc in response.tool_calls]}
            )
            
        return {"messages": [response]}

    # Simple tool execution function (replaces ToolNode)
    def execute_tools(state: MessagesState):
        from langchain_core.messages import ToolMessage
        messages = state["messages"]
        last_message = messages[-1]
        
        # Simple tool execution without ToolNode
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            # Execute tools manually
            tool_messages = []
            from backend.infrastructure.agent_audit_service import AgentAuditService
            from backend.shared.utils.logger import correlation_id_var
            
            audit_service = AgentAuditService()
            session_id = correlation_id_var.get() or "unknown_session"

            tools_by_name = {t.name: t for t in tools}
            for tool_call in last_message.tool_calls:
                tool = tools_by_name.get(tool_call['name'])
                if tool is None:
                    # Every tool call needs a reply or the provider rejects the next turn
                    tool_messages.append(ToolMessage(
                        content=f"Unknown tool '{tool_call['name']}'. Available: {', '.join(tools_by_name)}",
                        tool_call_id=tool_call['id'],
                        status="error",
                    ))
                    continue
                try:
                    result = tool.invoke(tool_call['args'])
                    audit_service.log_tool_execution(
                        tool_name=tool.name,
                        args=tool_call['args'],
                        result=str(result),
                        session_id=session_id,
                        status="success"
                    )
                    tool_messages.append(ToolMessage(content=str(result), tool_call_id=tool_call['id']))
                except Exception as e:
                    # Report the failure to the model instead of aborting the whole chat turn
                    audit_service.log_tool_execution(
                        tool_name=tool.name,
                        args=tool_call['args'],
                        result=str(e),
                        session_id=session_id,
                        status="failure"
                    )
                    tool_messages.append(ToolMessage(
                        content=f"Tool error: {e}",
                        tool_call_id=tool_call['id'],
                        status="error",
                    ))
            return {"messages": tool_messages}
        return {"messages": []}

    # Graph
    builder = StateGraph(MessagesState)

    # Define nodes: these do the work
    builder.add_node("assistant", assistant)
    builder.add_node("tools", execute_tools)

    # Define edges: these determine how the control flow moves
    builder.add_edge(START, "assistant")
    
    # Simple conditional logic (replaces tools_condition)
    def should_continue(state: MessagesState):
        messages = state["messages"]
        last_message = messages[-1]
        if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
            return "tools"
        return "__end__"
    
    builder.add_conditional_edges("assistant", should_continue)
    builder.add_edge("tools", "assistant")
    return builder.compile()

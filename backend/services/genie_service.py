"""
Genie AI Service - Query Databricks Genie Space for insights

Integrates with Metis - Sales KPI Analytics Genie space
to provide AI-powered insights and natural language queries.
"""

from typing import Dict, Any, Optional
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
import os


class GenieService:
    """Service for interacting with Databricks Genie spaces"""
    
    def __init__(self):
        """Initialize Genie service with app credentials"""
        self.config = Config()
        self.workspace = WorkspaceClient(config=self.config)
        
        # Genie space ID from app resources
        self.genie_space_id = "01f10b2015dc1186928a78ee0bb4869f"
        
    async def ask_question(self, question: str) -> Dict[str, Any]:
        """
        Ask a natural language question to the Genie space
        
        Args:
            question: Natural language question about KPIs/data
            
        Returns:
            Dict with answer, SQL query, and any visualizations
        """
        try:
            # Create a conversation in the Genie space
            conversation = self.workspace.genie.create_conversation(
                space_id=self.genie_space_id
            )
            
            # Ask the question
            message = self.workspace.genie.create_message(
                space_id=self.genie_space_id,
                conversation_id=conversation.conversation_id,
                content=question
            )
            
            # Wait for the response
            response = self.workspace.genie.get_message(
                space_id=self.genie_space_id,
                conversation_id=conversation.conversation_id,
                message_id=message.id
            )
            
            return {
                "question": question,
                "answer": response.content,
                "sql": getattr(response, 'sql', None),
                "status": "success"
            }
            
        except Exception as e:
            print(f"Error querying Genie: {e}")
            return {
                "question": question,
                "answer": f"Unable to get AI insights: {str(e)}",
                "status": "error"
            }
    
    async def get_suggested_questions(self) -> list[str]:
        """
        Get suggested questions based on the Genie space context
        
        Returns:
            List of suggested question strings
        """
        # Pre-defined suggestions based on the Metis space capabilities
        return [
            "What is the monthly sum of won amount over the current quarter?",
            "Which sales market has the highest pipeline value?",
            "What are the distributions of opportunities by sales channel?",
            "Identify interesting outliers in the won opportunities",
            "How does close rate compare across product groups?",
            "What is the trend in created pipeline over the last 90 days?",
            "Which segment is underperforming against targets?",
            "What's driving the change in active pipeline?"
        ]
    
    async def get_anomalies(self, metric: str = "won_pipeline") -> Dict[str, Any]:
        """
        Get AI-detected anomalies for a specific metric
        
        Args:
            metric: KPI metric name to analyze
            
        Returns:
            Dict with detected anomalies and explanations
        """
        question = f"Identify outliers and anomalies in {metric} over the current quarter. What's unusual?"
        return await self.ask_question(question)
    
    async def explain_change(self, metric: str, change_percent: float) -> Dict[str, Any]:
        """
        Get AI explanation for why a metric changed
        
        Args:
            metric: KPI metric name
            change_percent: Percentage change to explain
            
        Returns:
            Dict with AI-generated explanation
        """
        direction = "increased" if change_percent > 0 else "decreased"
        question = f"Why has {metric} {direction} by {abs(change_percent):.1f}% recently? What are the key drivers?"
        return await self.ask_question(question)

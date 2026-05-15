"""
Genie AI Service - Query Databricks Genie Space for insights

Integrates with Metis - Sales KPI Analytics Genie space
to provide AI-powered insights and natural language queries.
"""

from typing import Dict, Any, Optional
from databricks.sdk.core import Config
import requests
import os
import time


class GenieService:
    """Service for interacting with Databricks Genie spaces"""
    
    def __init__(self):
        """Initialize Genie service with app credentials"""
        self.config = Config()
        
        # Genie space ID from app resources
        self.genie_space_id = "01f10b2015dc1186928a78ee0bb4869f"
        
        # Get OAuth credentials
        self.base_url = f"https://{self.config.host}"
        self.access_token = None
        self._authenticate()
    
    def _authenticate(self):
        """Get OAuth access token using service principal credentials"""
        try:
            # Use the config's authenticate method to get token
            auth = self.config.authenticate()
            if auth and hasattr(auth, '__call__'):
                # Get the Authorization header
                header = auth()
                if isinstance(header, dict) and 'Authorization' in header:
                    self.access_token = header['Authorization'].replace('Bearer ', '')
                elif isinstance(header, str):
                    self.access_token = header.replace('Bearer ', '')
            
            if not self.access_token:
                print("Warning: Could not get OAuth token for Genie")
        except Exception as e:
            print(f"Warning: Genie authentication failed: {e}")
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make authenticated request to Databricks API"""
        if not self.access_token:
            raise Exception("Not authenticated - no access token available")
        
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()
        
    async def ask_question(self, question: str) -> Dict[str, Any]:
        """
        Ask a natural language question to the Genie space
        
        Args:
            question: Natural language question about KPIs/data
            
        Returns:
            Dict with answer, SQL query, and any visualizations
        """
        try:
            # Step 1: Create a conversation
            conversation_response = self._make_request(
                "POST",
                f"/api/2.0/genie/spaces/{self.genie_space_id}/conversations",
                json={}
            )
            conversation_id = conversation_response.get("conversation_id")
            
            if not conversation_id:
                raise Exception("Failed to create conversation")
            
            # Step 2: Send the message
            message_response = self._make_request(
                "POST",
                f"/api/2.0/genie/spaces/{self.genie_space_id}/conversations/{conversation_id}/messages",
                json={"content": question}
            )
            message_id = message_response.get("id")
            
            if not message_id:
                raise Exception("Failed to send message")
            
            # Step 3: Poll for the response (Genie is async)
            max_attempts = 30  # 30 seconds max wait
            for attempt in range(max_attempts):
                time.sleep(1)
                
                message_status = self._make_request(
                    "GET",
                    f"/api/2.0/genie/spaces/{self.genie_space_id}/conversations/{conversation_id}/messages/{message_id}"
                )
                
                status = message_status.get("status")
                if status == "COMPLETED":
                    # Get the answer
                    attachments = message_status.get("attachments", [])
                    answer_text = message_status.get("content", "No answer provided")
                    
                    # Extract SQL if available
                    sql_query = None
                    for attachment in attachments:
                        if attachment.get("query"):
                            sql_query = attachment["query"].get("query")
                            break
                    
                    return {
                        "question": question,
                        "answer": answer_text,
                        "sql": sql_query,
                        "status": "success"
                    }
                elif status == "FAILED" or status == "ERROR":
                    error_msg = message_status.get("error", "Query failed")
                    return {
                        "question": question,
                        "answer": f"Unable to process question: {error_msg}",
                        "status": "error"
                    }
            
            # Timeout
            return {
                "question": question,
                "answer": "Query timed out. Please try a simpler question.",
                "status": "timeout"
            }
            
        except Exception as e:
            print(f"Error querying Genie: {e}")
            import traceback
            traceback.print_exc()
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

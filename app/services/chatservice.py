from openai import OpenAI
from typing import List, Dict, Any
import logging
import json
from ..config import settings
from ..models import ChatMessage

logger = logging.getLogger(__name__)

class ChatService:
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("ChatService initialized with OpenAI client")

    def get_chat_history(self, user_id: str) -> List[ChatMessage]:
        """Get chat history for a user"""
        # TODO: Implement database retrieval
        return []

    async def analyze_user_prompt(self, user_id: str, prompt: str) -> str:
        """
        Analyze user prompt using OpenAI to determine if it's a buildable API, needs clarification, or is nonsense.
        Routes to appropriate function based on analysis.
        """
        try:
            logger.info(f"Analyzing prompt for user {user_id}: {prompt[:100]}...")
            
            system_prompt = """You are an AI assistant that analyzes user requests for API generation. 
            Your job is to determine if a user's request is:
            1. BUILDABLE - Clear, specific, and technically feasible as an API
            2. NEEDS_CLARIFICATION - Has potential but needs more details or clarification
            3. NOT_BUILDABLE - Vague, nonsensical, impossible, or inappropriate
            
            Respond with ONLY a JSON object in this exact format:
            {
                "decision": "BUILDABLE" | "NEEDS_CLARIFICATION" | "NOT_BUILDABLE",
                "confidence": 0.0-1.0,
                "reasoning": "Brief explanation of your decision",
                "questions": ["list of questions if clarification needed"] or null
            }
            
            Examples of BUILDABLE requests:
            - "Create an API that analyzes text sentiment"
            - "Build an API that converts images to text using OCR"
            - "Make an API that summarizes long documents"
            
            Examples of NEEDS_CLARIFICATION:
            - "Create an API for my business" (too vague)
            - "Build something with AI" (no specific functionality)
            - "Make an API that processes data" (what kind of data?)
            
            Examples of NOT_BUILDABLE:
            - "Create an API that hacks systems"
            - "Build an API that predicts lottery numbers"
            - "Make an API that violates privacy laws"
            - Complete nonsense or gibberish
            """
            
            user_prompt = f"Analyze this API request: {prompt}"
            
            response = self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )
            
            analysis_result = response.choices[0].message.content.strip()
            logger.info(f"Analysis result: {analysis_result}")
            
            # Parse the JSON response
            try:
                analysis = json.loads(analysis_result)
                decision = analysis.get("decision", "NOT_BUILDABLE")
                
                # Route to appropriate function based on decision
                if decision == "BUILDABLE":
                    return await self.IcanBuildThis(user_id, prompt)
                elif decision == "NEEDS_CLARIFICATION":
                    questions = analysis.get("questions", [])
                    return await self.AskMoreQuestions(user_id, prompt, questions)
                else:
                    return await self.ICantBuildThis(user_id, prompt)
                    
            except json.JSONDecodeError:
                logger.error(f"Failed to parse analysis result: {analysis_result}")
                return await self.ICantBuildThis(user_id, prompt)
                
        except Exception as e:
            logger.error(f"Error analyzing prompt: {str(e)}")
            return await self.ICantBuildThis(user_id, prompt)

    async def CanIBuildThis(self, user_id: str, prompt: str) -> str:
        """Main entry point for prompt analysis"""
        return await self.analyze_user_prompt(user_id, prompt)

    async def AskMoreQuestions(self, user_id: str, prompt: str, questions: List[str] = None) -> str:
        """Handle cases where more clarification is needed"""
        if not questions:
            questions = [
                "What specific functionality should the API provide?",
                "What type of input data will the API receive?",
                "What should the API return as output?",
                "Are there any specific requirements or constraints?"
            ]
        
        response = {
            "status": "needs_clarification",
            "message": "I need more information to build this API for you.",
            "questions": questions,
            "original_prompt": prompt
        }
        
        logger.info(f"Asking for clarification for user {user_id}")
        return json.dumps(response, indent=2)

    async def IcanBuildThis(self, user_id: str, prompt: str) -> str:
        """Handle buildable API requests"""
        response = {
            "status": "buildable",
            "message": "Great! I can build this API for you.",
            "prompt": prompt,
            "next_steps": [
                "I'll analyze your requirements",
                "Generate the API code",
                "Create documentation",
                "Provide testing examples"
            ]
        }
        
        logger.info(f"Confirmed buildable API for user {user_id}")
        return json.dumps(response, indent=2)

    async def ICantBuildThis(self, user_id: str, prompt: str) -> str:
        """Handle non-buildable requests"""
        response = {
            "status": "not_buildable",
            "message": "I'm sorry, but I can't build this API.",
            "reasons": [
                "The request may be too vague or unclear",
                "The functionality might not be technically feasible",
                "The request could involve inappropriate or harmful content"
            ],
            "suggestions": [
                "Try to be more specific about what you want the API to do",
                "Provide examples of input and expected output",
                "Focus on legitimate business or educational use cases"
            ]
        }
        
        logger.info(f"Rejected API request for user {user_id}")
        return json.dumps(response, indent=2)




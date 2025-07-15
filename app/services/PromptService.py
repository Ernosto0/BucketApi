from openai import OpenAI
from typing import List, Dict, Any
import logging
import json
from ..config import settings
from ..models import ChatMessage

logger = logging.getLogger(__name__)

class PromptServiceBuild:
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
            4. MODIFY_REQUEST - The user wants to modify an existing API (contains words like "modify", "change", "update", "edit", "improve", "add to", "remove from")
            
            Respond with ONLY a JSON object in this exact format:
            {
                "decision": "BUILDABLE" | "NEEDS_CLARIFICATION" | "NOT_BUILDABLE" | "MODIFY_REQUEST",
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
            
            Examples of MODIFY_REQUEST:
            - "Modify my last API to also return confidence scores"
            - "Change the API to handle PDF files"
            - "Update the sentiment API to support multiple languages"
            - "Add error handling to my API"
            - "Improve the response format"
            
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
                elif decision == "MODIFY_REQUEST":
                    return await self.HandleModifyRequest(user_id, prompt)
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

    async def HandleModifyRequest(self, user_id: str, prompt: str) -> str:
        """Handle modification requests for existing APIs"""
        response = {
            "status": "modify_request",
            "message": "I understand you want to modify an existing API.",
            "prompt": prompt,
            "instructions": [
                "If you have a recently generated API in this chat, you can use the 'Modify' button",
                "For saved APIs, please specify which API you want to modify",
                "Describe what changes you want to make to the API"
            ],
            "next_steps": [
                "Click the 'Modify' button on your last generated API",
                "Or tell me which saved API you want to modify",
                "Specify exactly what changes you need"
            ]
        }
        
        logger.info(f"Detected modify request for user {user_id}")
        return json.dumps(response, indent=2)


    


class PromptServiceModify:
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("PromptServiceModify initialized with OpenAI client")

    async def analyze_modify_prompt(self, user_id: str, prompt: str, existing_api_code: str = None) -> str:
        """
        Analyze user modification request using OpenAI to determine what changes need to be made.
        """
        try:
            logger.info(f"Analyzing modify prompt for user {user_id}: {prompt[:100]}...")
            
            system_prompt = """You are an AI assistant that analyzes user requests for API modifications. 
            Your job is to determine what type of modification the user wants:
            
            1. ADD_FEATURE - Adding new functionality to existing API
            2. MODIFY_RESPONSE - Changing response format or structure
            3. ADD_VALIDATION - Adding input validation or error handling
            4. CHANGE_LOGIC - Modifying core business logic
            5. ADD_ENDPOINT - Adding new endpoints to the API
            6. OPTIMIZE_CODE - Performance improvements or code optimization
            7. FIX_ISSUE - Bug fixes or error corrections
            8. UNCLEAR_REQUEST - Modification request is too vague
            
            Respond with ONLY a JSON object in this exact format:
            {
                "modification_type": "ADD_FEATURE" | "MODIFY_RESPONSE" | "ADD_VALIDATION" | "CHANGE_LOGIC" | "ADD_ENDPOINT" | "OPTIMIZE_CODE" | "FIX_ISSUE" | "UNCLEAR_REQUEST",
                "confidence": 0.0-1.0,
                "reasoning": "Brief explanation of what needs to be modified",
                "specific_changes": ["list of specific changes to make"],
                "questions": ["list of clarification questions if needed"] or null,
                "complexity": "LOW" | "MEDIUM" | "HIGH"
            }
            
            Examples:
            - "Add error handling" -> ADD_VALIDATION
            - "Change response to include timestamps" -> MODIFY_RESPONSE  
            - "Add a new endpoint for user profiles" -> ADD_ENDPOINT
            - "Make the API faster" -> OPTIMIZE_CODE
            - "Fix the bug where it crashes on empty input" -> FIX_ISSUE
            - "Add sentiment analysis feature" -> ADD_FEATURE
            - "Change the sorting algorithm" -> CHANGE_LOGIC
            """
            
            user_prompt = f"Analyze this API modification request: {prompt}"
            if existing_api_code:
                user_prompt += f"\n\nExisting API code:\n{existing_api_code[:1000]}..."
            
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
            logger.info(f"Modify analysis result: {analysis_result}")
            
            # Parse the JSON response
            try:
                analysis = json.loads(analysis_result)
                modification_type = analysis.get("modification_type", "UNCLEAR_REQUEST")
                
                # Route to appropriate function based on modification type
                if modification_type == "UNCLEAR_REQUEST":
                    questions = analysis.get("questions", [])
                    return await self.AskForClarification(user_id, prompt, questions)
                else:
                    return await self.ProcessModification(user_id, prompt, analysis)
                    
            except json.JSONDecodeError:
                logger.error(f"Failed to parse modification analysis result: {analysis_result}")
                return await self.AskForClarification(user_id, prompt)
                
        except Exception as e:
            logger.error(f"Error analyzing modify prompt: {str(e)}")
            return await self.AskForClarification(user_id, prompt)

    async def AskForClarification(self, user_id: str, prompt: str, questions: List[str] = None) -> str:
        """Handle cases where modification request needs clarification"""
        if not questions:
            questions = [
                "What specific changes do you want to make to the API?",
                "Which part of the API functionality should be modified?",
                "What should the new behavior be?",
                "Are you looking to add, remove, or change existing features?"
            ]
        
        response = {
            "status": "needs_clarification",
            "message": "I need more details about what you want to modify.",
            "questions": questions,
            "original_prompt": prompt,
            "suggestions": [
                "Be specific about which part of the API to modify",
                "Describe the desired outcome after modification",
                "Provide examples if possible"
            ]
        }
        
        logger.info(f"Asking for modification clarification for user {user_id}")
        return json.dumps(response, indent=2)

    async def ProcessModification(self, user_id: str, prompt: str, analysis: Dict[str, Any]) -> str:
        """Process a clear modification request"""
        modification_type = analysis.get("modification_type")
        specific_changes = analysis.get("specific_changes", [])
        complexity = analysis.get("complexity", "MEDIUM")
        
        response = {
            "status": "modification_ready",
            "message": "I understand what you want to modify.",
            "modification_type": modification_type,
            "complexity": complexity,
            "prompt": prompt,
            "planned_changes": specific_changes,
            "next_steps": [
                "I'll analyze your existing API code",
                "Apply the requested modifications",
                "Test the changes for compatibility",
                "Provide you with the updated API"
            ],
            "estimated_effort": self._get_effort_estimate(complexity)
        }
        
        logger.info(f"Processing {modification_type} modification for user {user_id}")
        return json.dumps(response, indent=2)

    async def CanIModifyThis(self, user_id: str, prompt: str, existing_api_code: str = None) -> str:
        """Main entry point for modification analysis"""
        return await self.analyze_modify_prompt(user_id, prompt, existing_api_code)

    def _get_effort_estimate(self, complexity: str) -> str:
        """Get effort estimate based on complexity"""
        estimates = {
            "LOW": "Quick modification (1-2 minutes)",
            "MEDIUM": "Standard modification (2-5 minutes)", 
            "HIGH": "Complex modification (5-10 minutes)"
        }
        return estimates.get(complexity, "Standard modification (2-5 minutes)")

    async def ValidateModificationRequest(self, user_id: str, prompt: str, api_context: Dict[str, Any]) -> str:
        """Validate if the modification request is feasible with the given API"""
        try:
            system_prompt = """You are validating if a modification request is feasible for a given API.
            
            Respond with ONLY a JSON object:
            {
                "feasible": true | false,
                "reasoning": "explanation of feasibility",
                "potential_issues": ["list of potential problems"] or null,
                "recommendations": ["list of recommendations"] or null
            }
            """
            
            user_prompt = f"""
            Modification request: {prompt}
            API context: {json.dumps(api_context, indent=2)}
            
            Is this modification feasible?
            """
            
            response = self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=300
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Error validating modification request: {str(e)}")
            return json.dumps({
                "feasible": False,
                "reasoning": "Error occurred during validation",
                "potential_issues": ["Validation system error"],
                "recommendations": ["Please try again or rephrase your request"]
            }, indent=2)
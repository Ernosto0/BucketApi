"""
Multi-Step Code Generation Service

Service for handling multi-step API code generation with streaming capabilities.
Breaks down code generation into configurable steps with real-time progress updates.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from ..code_generation_config.multi_step_config import MultiStepConfig, GenerationMode, StepType
from ..prompts.claude.prompt_loader import load_claude_prompt, format_claude_prompt
from .claude_service import claude_service
from .usage_service import usage_service

logger = logging.getLogger(__name__)

@dataclass
class StepResult:
    """Result of a single generation step"""
    step_id: str
    step_name: str
    step_type: str
    success: bool
    content: str
    error: Optional[str] = None
    execution_time: float = 0.0
    tokens_used: int = 0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class GenerationSession:
    """Represents a multi-step generation session"""
    session_id: str
    user_id: str
    prompt: str
    pipeline_name: str
    mode: GenerationMode
    started_at: datetime
    steps_completed: List[StepResult]
    current_step: Optional[str] = None
    total_tokens_used: int = 0
    total_execution_time: float = 0.0
    final_code: Optional[str] = None
    final_documentation: Optional[str] = None
    error: Optional[str] = None
    completed_at: Optional[datetime] = None
    
    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None
    
    @property
    def progress_percentage(self) -> float:
        if not hasattr(self, '_total_steps'):
            return 0.0
        return (len(self.steps_completed) / self._total_steps) * 100

class StreamEvent:
    """SSE event types for streaming"""
    STEP_START = "step_start"
    STEP_PROGRESS = "step_progress" 
    STEP_COMPLETE = "step_complete"
    STEP_ERROR = "step_error"
    SESSION_COMPLETE = "session_complete"
    SESSION_ERROR = "session_error"
    HEARTBEAT = "heartbeat"

class MultiStepGenerationService:
    """Service for multi-step code generation with streaming support"""
    
    def __init__(self):
        self.config = MultiStepConfig()
        self.active_sessions: Dict[str, GenerationSession] = {}
        
    async def start_generation(
        self,
        prompt: str,
        user_id: str,
        sample_input: Optional[str] = None,
        expected_output: Optional[str] = None,
        api_key_id: Optional[str] = None,
        pipeline_name: str = "full_pipeline",
        mode: GenerationMode = GenerationMode.NORMAL
    ) -> str:
        """Start a new multi-step generation session"""
        
        session_id = str(uuid.uuid4())
        
        # Validate pipeline
        if not self.config.validate_pipeline(pipeline_name):
            raise ValueError(f"Invalid pipeline: {pipeline_name}")
        
        # Create session
        session = GenerationSession(
            session_id=session_id,
            user_id=user_id,
            prompt=prompt,
            pipeline_name=pipeline_name,
            mode=mode,
            started_at=datetime.now(),
            steps_completed=[]
        )
        
        # Store additional context
        session.sample_input = sample_input
        session.expected_output = expected_output
        session.api_key_id = api_key_id
        session._total_steps = len(self.config.get_steps_config(pipeline_name))
        
        self.active_sessions[session_id] = session
        
        logger.info(f"Started generation session {session_id} for user {user_id} with pipeline {pipeline_name}")
        
        return session_id
    
    async def generate_normal_mode(self, session_id: str) -> Dict[str, Any]:
        """Execute generation in normal mode (single response after all steps)"""
        
        session = self.active_sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")
            
        try:
            logger.info(f"Starting normal mode generation for session {session_id}")
            
            # Execute all steps sequentially
            steps_config = self.config.get_steps_config(session.pipeline_name)
            step_outputs = {}
            
            for step_config in steps_config:
                step_result = await self._execute_step(session, step_config, step_outputs)
                session.steps_completed.append(step_result)
                
                if not step_result.success:
                    # Handle step failure based on configuration
                    if not self.config.ERROR_CONFIG["continue_on_step_failure"]:
                        raise Exception(f"Step {step_config['id']} failed: {step_result.error}")
                    logger.warning(f"Step {step_config['id']} failed but continuing: {step_result.error}")
                else:
                    step_outputs[step_config['id']] = step_result.content
            
            # Extract final results
            logger.info(f"Completed steps: {[step.step_id for step in session.steps_completed]}")
            logger.info(f"Step outputs available: {list(step_outputs.keys())}")
            
            session.final_code = self._extract_final_code(step_outputs)
            session.final_documentation = self._extract_final_documentation(step_outputs)
            session.completed_at = datetime.now()
            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
            
            logger.info(f"Normal mode generation completed for session {session_id}")
            logger.info(f"Final code length: {len(session.final_code) if session.final_code else 0} characters")
            
            return {
                "session_id": session_id,
                "success": True,
                "mode": "normal",
                "final_code": session.final_code,
                "final_documentation": session.final_documentation,
                "steps_completed": [asdict(step) for step in session.steps_completed],
                "total_execution_time": session.total_execution_time,
                "total_tokens_used": session.total_tokens_used,
                "completed_at": session.completed_at.isoformat()
            }
            
        except Exception as e:
            session.error = str(e)
            session.completed_at = datetime.now()
            logger.error(f"Normal mode generation failed for session {session_id}: {str(e)}")
            
            return {
                "session_id": session_id,
                "success": False,
                "mode": "normal", 
                "error": str(e),
                "steps_completed": [asdict(step) for step in session.steps_completed],
                "failed_at": session.completed_at.isoformat()
            }
    
    async def generate_streaming_mode(self, session_id: str) -> AsyncGenerator[str, None]:
        """Execute generation in streaming mode with real-time updates"""
        
        session = self.active_sessions.get(session_id)
        if not session:
            yield self._format_sse_event(StreamEvent.SESSION_ERROR, {"error": f"Session not found: {session_id}"})
            return
            
        try:
            logger.info(f"Starting streaming mode generation for session {session_id}")
            
            # Send session start event
            yield self._format_sse_event(StreamEvent.STEP_START, {
                "session_id": session_id,
                "mode": "streaming",
                "pipeline": session.pipeline_name,
                "total_steps": session._total_steps,
                "message": "🚀 Starting multi-step code generation..."
            })
            
            # Execute all steps with streaming updates
            steps_config = self.config.get_steps_config(session.pipeline_name)
            step_outputs = {}
            
            for i, step_config in enumerate(steps_config):
                # Send step start event
                yield self._format_sse_event(StreamEvent.STEP_START, {
                    "step_id": step_config["id"],
                    "step_name": step_config["name"],
                    "step_number": i + 1,
                    "total_steps": len(steps_config),
                    "message": step_config["streaming_message"]
                })
                
                # Execute the step
                step_result = await self._execute_step(session, step_config, step_outputs)
                session.steps_completed.append(step_result)
                
                # Send step complete/error event
                if step_result.success:
                    step_outputs[step_config['id']] = step_result.content
                    yield self._format_sse_event(StreamEvent.STEP_COMPLETE, {
                        "step_id": step_config["id"],
                        "step_name": step_config["name"],
                        "step_number": i + 1,
                        "execution_time": step_result.execution_time,
                        "tokens_used": step_result.tokens_used,
                        "content_preview": step_result.content[:200] + "..." if len(step_result.content) > 200 else step_result.content,
                        "message": f"✅ {step_config['name']} completed successfully"
                    })
                else:
                    yield self._format_sse_event(StreamEvent.STEP_ERROR, {
                        "step_id": step_config["id"],
                        "step_name": step_config["name"],
                        "step_number": i + 1,
                        "error": step_result.error,
                        "message": f"❌ {step_config['name']} failed: {step_result.error}"
                    })
                    
                    if not self.config.ERROR_CONFIG["continue_on_step_failure"]:
                        break
                
                # Send progress update
                progress = ((i + 1) / len(steps_config)) * 100
                yield self._format_sse_event(StreamEvent.STEP_PROGRESS, {
                    "progress": progress,
                    "steps_completed": i + 1,
                    "total_steps": len(steps_config)
                })
            
            # Finalize session
            session.final_code = self._extract_final_code(step_outputs)
            session.final_documentation = self._extract_final_documentation(step_outputs)
            session.completed_at = datetime.now()
            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
            
            # Send session complete event
            yield self._format_sse_event(StreamEvent.SESSION_COMPLETE, {
                "session_id": session_id,
                "final_code": session.final_code,
                "final_documentation": session.final_documentation,
                "total_execution_time": session.total_execution_time,
                "total_tokens_used": session.total_tokens_used,
                "steps_completed": len(session.steps_completed),
                "message": "🎉 Multi-step code generation completed successfully!"
            })
            
            logger.info(f"Streaming mode generation completed for session {session_id}")
            
        except Exception as e:
            session.error = str(e)
            session.completed_at = datetime.now()
            logger.error(f"Streaming mode generation failed for session {session_id}: {str(e)}")
            
            yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                "session_id": session_id,
                "error": str(e),
                "message": f"❌ Generation failed: {str(e)}"
            })
    
    async def _execute_step(
        self, 
        session: GenerationSession, 
        step_config: Dict[str, Any], 
        previous_outputs: Dict[str, str]
    ) -> StepResult:
        """Execute a single generation step"""
        
        start_time = time.time()
        step_id = step_config["id"]
        
        logger.info(f"Executing step {step_id} for session {session.session_id}")
        
        try:
            # Load prompt template
            prompt_template_name = step_config["prompt_template"]
            prompt_config = load_claude_prompt(prompt_template_name)
            
            # Prepare template variables
            template_vars = {
                "prompt": session.prompt,
                "original_prompt": session.prompt,
                "sample_input_section": f"\nSample Input: {session.sample_input}" if session.sample_input else "",
                "expected_output_section": f"\nExpected Output: {session.expected_output}" if session.expected_output else "",
            }
            
            # Add previous step outputs to template vars
            for output_id, output_content in previous_outputs.items():
                template_vars[output_id.replace("step", "").replace("_", "")] = output_content
                
            # Special handling for specific steps with fallbacks
            if step_id == "step1_analysis_design":
                # First step, no special handling needed
                pass
            elif step_id == "step2_implementation":
                template_vars["analysis_design"] = previous_outputs.get("step1_analysis_design",
                    f"Basic requirements analysis and design based on: {session.prompt}")
            elif step_id == "step3_testing":
                template_vars["implemented_code"] = previous_outputs.get("step2_implementation",
                    "async def run(file_bytes=None, input_data=None):\n    return {'result': 'API implementation', 'message': 'success'}")
                template_vars["analysis_design"] = previous_outputs.get("step1_analysis_design",
                    f"Basic requirements analysis and design based on: {session.prompt}")
            
            # Format prompts
            system_prompt, user_prompt = format_claude_prompt(prompt_config, **template_vars)
            
            # Make Claude API call
            response = await claude_service._make_claude_request(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                user_id=session.user_id,
                api_key_id=session.api_key_id,
                operation_type=step_config.get("operation_type", "multi_step_generation"),
                api_slug=f"multi_step_{step_id}"
            )
            
            execution_time = time.time() - start_time
            
            # Estimate tokens used (rough approximation)
            tokens_used = len(response) // 4  # Rough estimate: 1 token ≈ 4 characters
            
            logger.info(f"Step {step_id} completed successfully in {execution_time:.2f}s")
            logger.info(f"Response length: {len(response)} characters")
            logger.debug(f"Response preview: {response[:200]}...")
            
            # For implementation steps, extract code from response
            if step_id == "step2_implementation":
                try:
                    # Use claude_service to extract code from response
                    extracted_code = claude_service._extract_code_from_response(response)
                    if extracted_code:
                        logger.info(f"Extracted code from {step_id}: {len(extracted_code)} characters")
                        content = extracted_code
                    else:
                        logger.warning(f"No code found in {step_id} response, using raw response")
                        content = response
                except Exception as e:
                    logger.warning(f"Code extraction failed for {step_id}: {e}, using raw response")
                    content = response
            else:
                content = response
            
            return StepResult(
                step_id=step_id,
                step_name=step_config["name"],
                step_type=step_config["type"],
                success=True,
                content=content,
                execution_time=execution_time,
                tokens_used=tokens_used
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            
            logger.error(f"Step {step_id} failed after {execution_time:.2f}s: {error_msg}")
            
            return StepResult(
                step_id=step_id,
                step_name=step_config["name"],
                step_type=step_config["type"],
                success=False,
                content="",
                error=error_msg,
                execution_time=execution_time,
                tokens_used=0
            )
    
    def _extract_final_code(self, step_outputs: Dict[str, str]) -> Optional[str]:
        """Extract the final code from step outputs"""
        logger.info(f"Extracting final code from step outputs: {list(step_outputs.keys())}")
        
        # Implementation step contains the final code
        if "step2_implementation" in step_outputs:
            code = step_outputs["step2_implementation"]
            logger.info(f"Found implementation code: {len(code) if code else 0} characters")
            return code
        
        logger.warning(f"No final code found in step outputs: {list(step_outputs.keys())}")
        return None
    
    def _extract_final_documentation(self, step_outputs: Dict[str, str]) -> Optional[str]:
        """Extract the final documentation from step outputs"""
        # Testing step contains documentation
        if "step3_testing" in step_outputs:
            return step_outputs["step3_testing"]
        return None
    
    def _format_sse_event(self, event_type: str, data: Dict[str, Any]) -> str:
        """Format data as SSE event"""
        event_data = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        return f"data: {json.dumps(event_data)}\n\n"
    
    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a generation session"""
        session = self.active_sessions.get(session_id)
        if not session:
            return None
            
        return {
            "session_id": session_id,
            "user_id": session.user_id,
            "pipeline_name": session.pipeline_name,
            "mode": session.mode.value,
            "started_at": session.started_at.isoformat(),
            "is_completed": session.is_completed,
            "progress_percentage": session.progress_percentage,
            "steps_completed": len(session.steps_completed),
            "total_steps": session._total_steps,
            "current_step": session.current_step,
            "total_tokens_used": session.total_tokens_used,
            "total_execution_time": session.total_execution_time,
            "error": session.error,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None
        }
    
    def cleanup_session(self, session_id: str) -> bool:
        """Clean up a completed session"""
        if session_id in self.active_sessions:
            del self.active_sessions[session_id]
            logger.info(f"Cleaned up session {session_id}")
            return True
        return False
    
    def get_available_pipelines(self) -> Dict[str, Any]:
        """Get information about available pipelines"""
        return self.config.get_pipeline_info()

# Create service instance
multi_step_generation_service = MultiStepGenerationService()

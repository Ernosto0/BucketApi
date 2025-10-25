"""
Multi-Step Code Generation Configuration

Configuration for the multi-step code generation pipeline that breaks down
API generation into multiple LLM calls with streaming capabilities.
"""

from typing import Dict, List, Any, Optional
from enum import Enum
from app.config import settings
class StepType(Enum):
    """Types of steps in the multi-step generation process"""
    ANALYSIS_DESIGN = "analysis_design"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"

class GenerationMode(Enum):
    """Generation modes for the multi-step system"""
    NORMAL = "normal"  # Single response after all steps
    STREAMING = "streaming"  # Real-time streaming updates

class MultiStepConfig:
    """Configuration for multi-step code generation"""
    
    # Default 3-step pipeline configuration
    DEFAULT_STEPS = [
        {
            "id": "step1_analysis_design",
            "name": "Analysis & Design",
            "type": StepType.ANALYSIS_DESIGN.value,
            "description": "Analyze requirements and design code structure",
            "prompt_template": "analyze_design",
            "model": settings.CLAUDE_MODEL,
            "temperature": 0.3,
            "max_tokens": 2000,
            "timeout": 45,
            "enabled": True,
            "dependencies": [],
            "output_format": "structured_text"
        },
        {
            "id": "step2_implementation",
            "name": "Code Implementation",
            "type": StepType.IMPLEMENTATION.value, 
            "description": "Generate complete working code",
            "prompt_template": "implement_code",
            "model": settings.CLAUDE_MODEL,
            "temperature": 0.3,
            "max_tokens": 4000,
            "timeout": 90,
            "enabled": True,
            "dependencies": ["step1_analysis_design"],
            "output_format": "code"
        },
        {
            "id": "step3_testing",
            "name": "Tests & Documentation",
            "type": StepType.TESTING.value,
            "description": "Generate tests, documentation, and usage examples",
            "prompt_template": "generate_tests_docs",
            "model": settings.CLAUDE_MODEL, 
            "temperature": 0.4,
            "max_tokens": 2500,
            "timeout": 60,
            "enabled": True,
            "dependencies": ["step2_implementation"],
            "output_format": "mixed"
        }
    ]
    
    # Configuration options
    STREAMING_CONFIG = {
        "chunk_size": 1024,
        "delay_between_chunks": 0.1,  # seconds
        "heartbeat_interval": 10,  # seconds
        "max_connection_time": 300,  # 5 minutes
        "buffer_size": 8192
    }
    
    NORMAL_MODE_CONFIG = {
        "consolidate_responses": True,
        "include_step_summaries": True,
        "final_validation": True
    }
    
    # Error handling and retry configuration
    ERROR_CONFIG = {
        "max_retries_per_step": 2,
        "retry_delay": 2,  # seconds
        "continue_on_step_failure": True,
        "fallback_to_single_step": True
    }
    
    # Custom pipeline configurations
    CUSTOM_PIPELINES = {
        "simple": {
            "name": "Simple Generation",
            "steps": ["step2_implementation"],  # Just implementation
            "description": "Single-step code generation"
        },
        "analysis_implementation": {
            "name": "Analysis + Implementation", 
            "steps": ["step1_analysis_design", "step2_implementation"],
            "description": "Two-step: analyze & design then implement"
        },
        "full_pipeline": {
            "name": "Full 3-Step Pipeline",
            "steps": ["step1_analysis_design", "step2_implementation", "step3_testing"],
            "description": "Complete 3-step generation process"
        }
    }

    @classmethod
    def get_steps_config(cls, pipeline_name: str = "full_pipeline") -> List[Dict[str, Any]]:
        """Get configuration for a specific pipeline"""
        if pipeline_name not in cls.CUSTOM_PIPELINES:
            pipeline_name = "full_pipeline"
            
        pipeline = cls.CUSTOM_PIPELINES[pipeline_name]
        step_ids = pipeline["steps"]
        
        # Filter steps based on pipeline
        return [step for step in cls.DEFAULT_STEPS if step["id"] in step_ids]
    
    @classmethod
    def get_step_by_id(cls, step_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific step configuration by ID"""
        for step in cls.DEFAULT_STEPS:
            if step["id"] == step_id:
                return step
        return None
    
    @classmethod
    def validate_pipeline(cls, pipeline_name: str) -> bool:
        """Validate that a pipeline configuration is valid"""
        try:
            steps = cls.get_steps_config(pipeline_name)
            
            # Check that all dependencies are met
            available_steps = set(step["id"] for step in steps)
            
            for step in steps:
                for dep in step.get("dependencies", []):
                    if dep not in available_steps:
                        return False
                        
            return True
        except Exception:
            return False
    
    @classmethod
    def get_pipeline_info(cls) -> Dict[str, Any]:
        """Get information about all available pipelines"""
        return {
            "available_pipelines": cls.CUSTOM_PIPELINES,
            "default_pipeline": "full_pipeline",
            "step_types": [t.value for t in StepType],
            "generation_modes": [m.value for m in GenerationMode]
        }

# Export configuration for easy import
multi_step_config = MultiStepConfig()

#!/usr/bin/env python3
"""
Demo script showing example generated APIs
These are examples of what the AI would generate
"""
import json
# Example 1: Text Processing API
def text_analyzer_example():
    """
    Example of a generated API for text analysis
    """
    import json
    import re
    from collections import Counter
    
    def run(file_bytes=None, input_data=None):
        '''
        Analyze text content and return word frequency and statistics
        '''
        try:
            if file_bytes:
                # Decode file content
                text = file_bytes.decode('utf-8')
            elif input_data and 'text' in input_data:
                text = input_data['text']
            else:
                return {"error": "No text provided", "message": "failed"}
            
            # Clean and tokenize text
            words = re.findall(r'\b\w+\b', text.lower())
            
            # Calculate statistics
            word_count = len(words)
            unique_words = len(set(words))
            word_frequency = dict(Counter(words).most_common(10))
            
            # Calculate readability (simple sentence count)
            sentences = len(re.findall(r'[.!?]+', text))
            avg_words_per_sentence = word_count / max(sentences, 1)
            
            result = {
                "word_count": word_count,
                "unique_words": unique_words,
                "sentence_count": sentences,
                "avg_words_per_sentence": round(avg_words_per_sentence, 2),
                "top_words": word_frequency,
                "text_preview": text[:100] + "..." if len(text) > 100 else text
            }
            
            return {"result": result, "message": "success"}
            
        except Exception as e:
            return {"error": str(e), "message": "failed"}

# Example 2: Data Validation API
def email_validator_example():
    """
    Example of a generated API for email validation
    """
    import json
    import re
    
    def run(file_bytes=None, input_data=None):
        '''
        Validate email addresses in provided data
        '''
        try:
            emails = []
            
            if file_bytes:
                # Extract emails from file content
                text = file_bytes.decode('utf-8')
                email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                emails = re.findall(email_pattern, text)
            elif input_data:
                if 'emails' in input_data:
                    emails = input_data['emails']
                elif 'email' in input_data:
                    emails = [input_data['email']]
                else:
                    return {"error": "No emails provided", "message": "failed"}
            
            # Validate each email
            valid_emails = []
            invalid_emails = []
            
            email_regex = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'
            
            for email in emails:
                if re.match(email_regex, email):
                    valid_emails.append(email)
                else:
                    invalid_emails.append(email)
            
            result = {
                "total_emails": len(emails),
                "valid_emails": valid_emails,
                "invalid_emails": invalid_emails,
                "valid_count": len(valid_emails),
                "invalid_count": len(invalid_emails),
                "validation_rate": round(len(valid_emails) / max(len(emails), 1) * 100, 2)
            }
            
            return {"result": result, "message": "success"}
            
        except Exception as e:
            return {"error": str(e), "message": "failed"}

# Example 3: JSON Data Processor
def json_processor_example():
    """
    Example of a generated API for processing JSON data
    """
    import json
    from datetime import datetime
    
    def run(file_bytes=None, input_data=None):
        '''
        Process and transform JSON data with statistics
        '''
        try:
            data = None
            
            if file_bytes:
                # Parse JSON from file
                content = file_bytes.decode('utf-8')
                data = json.loads(content)
            elif input_data:
                data = input_data
            else:
                return {"error": "No data provided", "message": "failed"}
            
            # Analyze data structure
            def analyze_structure(obj, path=""):
                stats = {"fields": 0, "nested_objects": 0, "arrays": 0, "null_values": 0}
                field_types = {}
                
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        current_path = f"{path}.{key}" if path else key
                        stats["fields"] += 1
                        
                        if value is None:
                            stats["null_values"] += 1
                            field_types[current_path] = "null"
                        elif isinstance(value, dict):
                            stats["nested_objects"] += 1
                            field_types[current_path] = "object"
                            nested_stats, nested_types = analyze_structure(value, current_path)
                            for k, v in nested_stats.items():
                                stats[k] += v
                            field_types.update(nested_types)
                        elif isinstance(value, list):
                            stats["arrays"] += 1
                            field_types[current_path] = f"array[{len(value)}]"
                        else:
                            field_types[current_path] = type(value).__name__
                
                return stats, field_types
            
            stats, field_types = analyze_structure(data)
            
            # Generate summary
            result = {
                "analysis_timestamp": datetime.now().isoformat(),
                "data_statistics": stats,
                "field_types": field_types,
                "data_size_estimate": len(json.dumps(data)) if data else 0,
                "processed_data": data  # Return the original data as well
            }
            
            return {"result": result, "message": "success"}
            
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON: {str(e)}", "message": "failed"}
        except Exception as e:
            return {"error": str(e), "message": "failed"}

if __name__ == "__main__":
    print("🤖 AI-Powered API Generator - Demo Examples")
    print("=" * 50)
    
    # Demo text analysis
    print("\n📝 Text Analysis API Example:")
    sample_text = "Hello world! This is a sample text for analysis. Hello again!"
    result1 = text_analyzer_example().run(input_data={"text": sample_text})
    print(json.dumps(result1, indent=2))
    
    # Demo email validation
    print("\n📧 Email Validation API Example:")
    sample_emails = ["test@example.com", "invalid-email", "user@domain.org"]
    result2 = email_validator_example().run(input_data={"emails": sample_emails})
    print(json.dumps(result2, indent=2))
    
    # Demo JSON processing
    print("\n🔍 JSON Processor API Example:")
    sample_json = {
        "user": {
            "name": "John Doe",
            "email": "john@example.com",
            "age": 30,
            "preferences": ["coding", "reading"]
        },
        "metadata": {
            "created": "2024-01-01",
            "active": True
        }
    }
    result3 = json_processor_example().run(input_data=sample_json)
    print(json.dumps(result3, indent=2)) 
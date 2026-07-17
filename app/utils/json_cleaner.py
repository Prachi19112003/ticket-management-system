import re

def clean_json_markdown(text: str) -> str:
    """
    Strips markdown code block wrappers (e.g. ```json ... ``` or ``` ... ```)
    from a string before passing it to json.loads().
    """
    if not text:
        return ""
    
    cleaned = text.strip()
    
    # Strip opening ```json or ```
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
        
    # Strip closing ```
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
        
    return cleaned.strip()

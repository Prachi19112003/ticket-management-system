import re
import html

def clean_email_body(raw_body: str) -> str:
    """
    Cleans raw email body text by:
    1. Stripping HTML markup, including <style> and <script> blocks.
    2. Unescaping HTML entities (e.g. &nbsp; to space).
    3. Truncating standard email signatures and greetings (e.g., lines starting with '--', 'Regards', 'Sincerely').
    """
    if not raw_body:
        return ""

    # Remove script and style tags and their contents
    text_content = re.sub(r"<(script|style|head)[^>]*>.*?</\1>", "", raw_body, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove HTML comments
    text_content = re.sub(r"<!--.*?-->", "", text_content, flags=re.DOTALL)
    
    # Replace block level tags and break tags with newlines to preserve lines
    text_content = re.sub(r"<br\s*/?>", "\n", text_content, flags=re.IGNORECASE)
    text_content = re.sub(r"</?(p|div|tr|li|ul|ol|h[1-6]|table|blockquote)[^>]*>", "\n", text_content, flags=re.IGNORECASE)
    
    # Strip remaining HTML tags
    text_content = re.sub(r"<[^>]+>", " ", text_content)
    
    # Unescape HTML entities
    text_content = html.unescape(text_content)

    # Split into lines to identify and truncate signatures
    raw_lines = text_content.splitlines()
    cleaned_lines = []

    # Signature trigger patterns (run against stripped lines)
    signature_patterns = [
        r"^--\s*$",                    # Standard sig dash '--'
        r"^(kind\s+)?regards,?\s*$",    # Regards / Kind regards
        r"^sincerely,?\s*$",           # Sincerely
        r"^thanks,?\s*$",              # Thanks
        r"^thank\s+you,?\s*$",         # Thank you
        r"^best,?\s*$",                # Best / Best regards
        r"^warm\s+regards,?\s*$",      # Warm regards
        r"^cheers,?\s*$"               # Cheers
    ]

    for line in raw_lines:
        stripped = line.strip()
        
        # Check if the line matches any signature pattern
        is_signature_start = False
        for pattern in signature_patterns:
            if re.match(pattern, stripped, re.IGNORECASE):
                is_signature_start = True
                break
        
        if is_signature_start:
            break
            
        cleaned_lines.append(stripped)

    # Join the lines and normalize whitespace
    cleaned_text = "\n".join(cleaned_lines).strip()
    
    # Replace 3 or more consecutive newlines with exactly 2
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    
    # Replace multiple horizontal spaces with a single space
    cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)
    
    return cleaned_text

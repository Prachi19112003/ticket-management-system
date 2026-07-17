import difflib

def compute_similarity_ratio(original: str, final: str) -> float:
    """
    Computes the standard SequenceMatcher similarity ratio (normalized to 0.0-1.0)
    between the original draft reply and the final sent text.
    1.0 means identical, 0.0 means completely different.
    """
    if not original and not final:
        return 1.0
    if not original or not final:
        return 0.0
    
    # Strip leading/trailing whitespaces to avoid penalty for extra/missing terminal linebreaks
    orig_clean = original.strip()
    final_clean = final.strip()
    
    matcher = difflib.SequenceMatcher(None, orig_clean, final_clean)
    return matcher.ratio()

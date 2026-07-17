from sentence_transformers import SentenceTransformer
from app.core.exceptions import EmbeddingException
from app.core.logging import logger

MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
_model: SentenceTransformer | None = None

def get_model() -> SentenceTransformer:
    """
    Retrieves or initializes the sentence-transformers model instance.
    Loads the model weights once (lazy-initialization with singleton pattern).
    """
    global _model
    if _model is None:
        try:
            logger.info("Initializing local embedding model", model=MODEL_NAME)
            _model = SentenceTransformer(MODEL_NAME)
            logger.info("Successfully loaded local embedding model", model=MODEL_NAME)
        except Exception as e:
            logger.critical("Failed to load local embedding model at startup", model=MODEL_NAME, error=str(e))
            raise EmbeddingException("Failed to load embedding model", details={"original_error": str(e)})
    return _model

def get_embedding(text: str) -> list[float]:
    """
    Generates a 768-dimension vector embedding for the input text using
    the local sentence-transformers all-mpnet-base-v2 model.

    NOTE: The first run of this script will automatically download the model
    files (~420MB) from Hugging Face. In production, this download step
    must happen at Docker image build time (within the Dockerfile) to avoid
    high latency and potential request timeouts on the first real request.
    """
    model = get_model()
    try:
        # Generate embedding as a numpy array, then convert to a list of floats
        embedding_array = model.encode(text, convert_to_numpy=True)
        return embedding_array.tolist()
    except Exception as e:
        logger.error("Failed to generate text embedding locally", error=str(e))
        raise EmbeddingException("Failed to generate embedding", details={"original_error": str(e)})

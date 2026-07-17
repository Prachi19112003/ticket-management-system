import numpy as np
from app.integrations.embedding_client import get_embedding
from app.core.exceptions import EmbeddingException
from app.core.logging import logger
from app.core.config import settings

class ClassificationService:
    def __init__(self) -> None:
        self.category_prototypes: dict[str, list[float]] = {}
        self.initialized = False

    def initialize_prototypes(self) -> None:
        """
        Pre-embeds the category exemplars and averages them to create
        zero-shot category prototype vectors.
        """
        if self.initialized:
            return

        # Predefined exemplar statements for each category
        exemplars = {
            "Sales": [
                "request a product quote and price listing",
                "pricing, licenses, custom plans, and billing inquiry",
                "interested in purchasing, order placement, and buying contracts",
                "discount requests, enterprise pricing, and deal negotiations"
            ],
            "Procurement": [
                "request for quote rfq and vendor selection",
                "purchase orders, invoices, supply chain billing, and delivery status",
                "supplier registration, onboarding, and logistics updates",
                "accounts payable, vendor accounts, and shipment lists"
            ],
            "General": [
                "customer support help desk inquiry and ticket submission",
                "technical support, login issues, password reset, and system error",
                "general feedback, product suggestions, bug reports, and features",
                "account cancellation, information change, and general questions"
            ]
        }

        try:
            logger.info("Initializing zero-shot classification prototype vectors...")
            for category, sentences in exemplars.items():
                embeddings = [get_embedding(s) for s in sentences]
                # Calculate the centroid (average) vector for the category
                avg_vector = np.mean(embeddings, axis=0).tolist()
                self.category_prototypes[category] = avg_vector
            self.initialized = True
            logger.info("Zero-shot classification prototypes initialized successfully.")
        except Exception as e:
            logger.error("Failed to initialize classification prototypes", error=str(e))
            raise EmbeddingException("Failed to initialize classifier", details={"original_error": str(e)})

    def classify_ticket(self, cleaned_body: str) -> tuple[str, float]:
        """
        Classifies a cleaned email body into Sales, Procurement, or General.
        Returns:
            tuple[str, float]: (predicted_category, confidence_score_between_0_and_1)
        """
        if not self.initialized:
            self.initialize_prototypes()

        try:
            # Generate the embedding vector for the ticket body
            ticket_embedding = get_embedding(cleaned_body)
            
            # Calculate cosine similarities against each prototype
            similarities = {}
            for category, prototype in self.category_prototypes.items():
                sim = self._cosine_similarity(ticket_embedding, prototype)
                similarities[category] = sim

            # Normalize similarities into probability distribution using Softmax
            categories = list(similarities.keys())
            raw_scores = [similarities[cat] for cat in categories]
            
            # A temperature of 0.05 scales the similarities (typically clustered 0.3-0.7) to a clear distribution
            probabilities = self._softmax(raw_scores, temperature=settings.CLASSIFICATION_TEMPERATURE)
            
            max_idx = int(np.argmax(probabilities))
            predicted_category = categories[max_idx]
            confidence = probabilities[max_idx]

            logger.info("Ticket classified", category=predicted_category, confidence=confidence)
            return predicted_category, confidence

        except Exception as e:
            logger.error("Failed to classify ticket locally, executing default fallback", error=str(e))
            # Fallback path: return "General" category with a default confidence ratio
            return "General", 1.0

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        a = np.array(v1)
        b = np.array(v2)
        denominator = np.linalg.norm(a) * np.linalg.norm(b)
        if denominator == 0:
            return 0.0
        return float(np.dot(a, b) / denominator)

    def _softmax(self, scores: list[float], temperature: float) -> list[float]:
        max_score = max(scores)
        # Shift scores for numerical stability
        shifted_scaled = [(s - max_score) / temperature for s in scores]
        exp_scores = [np.exp(s) for s in shifted_scaled]
        sum_exp = sum(exp_scores)
        if sum_exp == 0:
            return [1.0 / len(scores)] * len(scores)
        return [float(e / sum_exp) for e in exp_scores]

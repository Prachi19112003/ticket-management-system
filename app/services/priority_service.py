class PriorityService:
    # Rule engine configuration dictionary (avoids hardcoding scoring logic inline)
    RULES_CONFIG = {
        "base_score": 15,
        "tier_multipliers": {
            "platinum": 1.6,
            "gold": 1.3,
            "silver": 1.1,
            "standard": 1.0
        },
        "keyword_scores": {
            "urgent": 25,
            "emergency": 30,
            "critical": 25,
            "broken": 20,
            "failed": 15,
            "error": 10,
            "complaint": 15,
            "refund": 20,
            "billing": 10,
            "down": 25
        },
        "wait_time_multiplier": 2.5,  # Add 2.5 points per hour of customer wait time
        "max_wait_time_bonus": 25      # Cap wait time bonus at 25 points
    }

    def calculate_priority(
        self,
        subject: str,
        body: str,
        customer_tier: str,
        wait_time_hours: float = 0.0
    ) -> int:
        """
        Calculates a priority score between 1 and 100 using a config-driven ruleset:
        1. Checks subject and body for high-priority keywords (subject matches get full points, body matches get half).
        2. Adds a wait-time bonus based on the hours passed since last interaction.
        3. Applies a multiplier based on the customer's subscription tier.
        4. Constrains the final output within the check constraint bounds of [1, 100].
        """
        config = self.RULES_CONFIG
        score = float(config["base_score"])
        
        subject_lower = subject.lower() if subject else ""
        body_lower = body.lower() if body else ""

        # 1. Evaluate keywords
        for kw, points in config["keyword_scores"].items():
            if kw in subject_lower:
                score += points
            elif kw in body_lower:
                score += (points / 2.0)  # Keywords in body carry 50% weight

        # 2. Add wait-time bonus
        wait_bonus = wait_time_hours * config["wait_time_multiplier"]
        wait_bonus = min(wait_bonus, config["max_wait_time_bonus"])
        score += wait_bonus

        # 3. Apply customer tier multiplier
        tier = customer_tier.lower() if customer_tier else "standard"
        multiplier = config["tier_multipliers"].get(tier, 1.0)
        score *= multiplier

        # 4. Round and clamp between 1 and 100
        final_score = int(round(score))
        return max(1, min(final_score, 100))

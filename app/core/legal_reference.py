# State-specific rent control acts
RENT_CONTROL_ACTS = {
    "Delhi":          "Delhi Rent Control Act 1958",
    "Maharashtra":    "Maharashtra Rent Control Act 1999",
    "Karnataka":      "Karnataka Rent Control Act 2001",
    "Tamil Nadu":     "Tamil Nadu Regulation of Rights and Responsibilities of Landlords and Tenants Act 2017",
    "West Bengal":    "West Bengal Premises Tenancy Act 1997",
    "Uttar Pradesh":  "Uttar Pradesh Urban Buildings (Regulation of Letting, Rent and Eviction) Act 1972",
    "Rajasthan":      "Rajasthan Rent Control Act 2001",
    "Gujarat":        "Gujarat Rent Control Act 1999",
    "Telangana":      "Telangana Rent Control Act 1960",
    "Andhra Pradesh": "Andhra Pradesh Buildings (Lease, Rent and Eviction) Control Act 1960",
    "Kerala":         "Kerala Buildings (Lease and Rent Control) Act 1965",
    "Punjab":         "East Punjab Rent Restriction Act 1949",
    "Haryana":        "Haryana Urban (Control of Rent and Eviction) Act 1973",
    "Madhya Pradesh": "Madhya Pradesh Accommodation Control Act 1961",
}

# Consumer forum tiers by claim amount (in INR)
CONSUMER_FORUM_TIERS = {
    "district": {
        "max_amount":  5_000_000,   # up to Rs. 50 lakh
        "description": "District Consumer Disputes Redressal Commission",
    },
    "state": {
        "max_amount":  20_000_000,  # Rs. 50 lakh to Rs. 2 crore
        "description": "State Consumer Disputes Redressal Commission",
    },
    "national": {
        "max_amount":  None,        # above Rs. 2 crore
        "description": "National Consumer Disputes Redressal Commission (NCDRC)",
    },
}


def get_consumer_forum_tier(claim_amount: float | None) -> str:
    if not claim_amount:
        return "district"
    if claim_amount <= 5_000_000:
        return "district"
    elif claim_amount <= 20_000_000:
        return "state"
    else:
        return "national"


def get_rent_control_act(state: str) -> str:
    return RENT_CONTROL_ACTS.get(state, "Transfer of Property Act 1882 (general)")


# Limitation periods (years) by dispute type
LIMITATION_PERIODS = {
    "rental_deposit":       3,
    "unpaid_salary":        3,
    "consumer_fraud":       2,   # Consumer Protection Act — 2 years
    "contract_breach":      3,
    "property_damage":      3,
    "loan_default":         3,
    "cheque_bounce":        1,   # NI Act — 1 month for complaint, 3 yr civil
    "defamation":           1,
    "wrongful_termination": 3,
    "pf_gratuity":          3,
    "employment_general":   3,
    "assault":              3,   # civil — criminal has no limitation
    "consumer_general":     2,
    "other":                3,
}


def get_limitation_period(dispute_category: str) -> int:
    return LIMITATION_PERIODS.get(dispute_category, 3)
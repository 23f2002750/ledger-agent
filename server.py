def answer_customer_question(rows, question):
    q = question.lower()

    # Number of distinct customers
    if (
        "how many" in q
        or "number of" in q
        or "count of" in q
        or "different customers" in q
        or "distinct customers" in q
    ):
        customers = set()

        for row in rows:
            if is_paid(row):
                customer = row.get("customer")

                if customer:
                    customers.add(customer)

        return str(len(customers))

    # Customer -> spending / revenue
    if any(
        phrase in q
        for phrase in [
            "spent",
            "spending",
            "revenue",
            "sales",
            "purchase",
            "purchases"
        ]
    ):
        spending = defaultdict(float)

        for row in rows:
            if is_paid(row):
                customer = row.get("customer")

                if customer:
                    spending[customer] += row_value(
                        row,
                        get_target_currency(question)
                    )

        if not spending:
            return "Unable to answer the question."

        if any(
            word in q
            for word in [
                "least",
                "lowest",
                "minimum"
            ]
        ):
            return min(
                spending,
                key=spending.get
            )

        return max(
            spending,
            key=spending.get
        )

    # Customer -> number of orders
    if "order" in q:
        counts = defaultdict(int)

        for row in rows:
            if is_paid(row):
                customer = row.get("customer")

                if customer:
                    counts[customer] += 1

        if not counts:
            return "Unable to answer the question."

        if any(
            word in q
            for word in [
                "least",
                "lowest",
                "minimum"
            ]
        ):
            return min(
                counts,
                key=counts.get
            )

        return max(
            counts,
            key=counts.get
        )

    return "Unable to answer the question."

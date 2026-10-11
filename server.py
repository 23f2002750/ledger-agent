from flask import Flask, request, jsonify
import json
import re
from datetime import datetime
from collections import defaultdict
from zoneinfo import ZoneInfo

app = Flask(__name__)

DATA_FILE = "ledger-export.json"

USD_PER_UNIT = {
    "USD": 1.0,
    "EUR": 1.08,
    "INR": 0.01169,
}

orders_cache = None


# --------------------------------------------------
# LOAD DATA
# --------------------------------------------------

def load_orders():
    global orders_cache

    if orders_cache is not None:
        return orders_cache

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        rows = [
            json.loads(line)
            for line in f
            if line.strip()
        ]

    # An order ID may occur multiple times.
    # Keep only the latest updated version.
    latest = {}

    for row in rows:
        order_id = row["id"]

        if (
            order_id not in latest
            or row["updated_at"] > latest[order_id]["updated_at"]
        ):
            latest[order_id] = row

    orders_cache = list(latest.values())

    print(f"Loaded {len(orders_cache)} current orders.")

    return orders_cache


# --------------------------------------------------
# CURRENCY
# --------------------------------------------------

def convert_currency(amount, from_currency, to_currency):
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency not in USD_PER_UNIT:
        raise ValueError(f"Unknown currency: {from_currency}")

    if to_currency not in USD_PER_UNIT:
        raise ValueError(f"Unknown currency: {to_currency}")

    # Convert source -> USD -> target
    usd_value = amount * USD_PER_UNIT[from_currency]

    return usd_value / USD_PER_UNIT[to_currency]


def row_value(row, target_currency="USD"):
    amount = float(row.get("amount", 0))
    source_currency = str(
        row.get("currency", "USD")
    ).upper()

    return convert_currency(
        amount,
        source_currency,
        target_currency
    )


def get_target_currency(question):
    q = question.lower()

    if re.search(r"\beur\b|\beuro\b|\beuros\b", q):
        return "EUR"

    if re.search(r"\binr\b|\brupees?\b|\brs\.?\b|₹", q):
        return "INR"

    if re.search(r"\busd\b|\bdollars?\b|\$", q):
        return "USD"

    # Assignment examples use USD and USD is
    # the natural default for monetary answers.
    return "USD"


# --------------------------------------------------
# DATES
# --------------------------------------------------

def business_date(row):
    dt = datetime.fromisoformat(
        row["created_at"].replace("Z", "+00:00")
    )

    return dt.astimezone(
        ZoneInfo("Asia/Kolkata")
    )


def get_month(question):
    months = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    for name, number in months.items():
        if name in question:
            match = re.search(
                r"\b(20\d{2})\b",
                question
            )

            if match:
                return int(match.group(1)), number

    return None


def filter_by_month(rows, question):
    month = get_month(question)

    if not month:
        return rows

    year, month_number = month

    return [
        row
        for row in rows
        if (
            business_date(row).year == year
            and business_date(row).month == month_number
        )
    ]


# --------------------------------------------------
# FILTERS
# --------------------------------------------------

def filter_by_region(rows, question):
    regions = [
        "north",
        "south",
        "east",
        "west",
        "central",
    ]

    for region in regions:
        if re.search(
            rf"\b{region}\b",
            question
        ):
            return [
                row for row in rows
                if str(
                    row.get("region", "")
                ).lower() == region
            ]

    return rows


def filter_by_product(rows, question):
    products = sorted(
        {
            str(row.get("product", ""))
            for row in rows
            if row.get("product")
        },
        key=len,
        reverse=True
    )

    q = question.lower()

    for product in products:
        if product.lower() in q:
            return [
                row for row in rows
                if str(
                    row.get("product", "")
                ).lower() == product.lower()
            ]

    return rows


def filter_by_customer(rows, question):
    customers = sorted(
        {
            str(row.get("customer", ""))
            for row in rows
            if row.get("customer")
        },
        key=len,
        reverse=True
    )

    q = question.lower()

    for customer in customers:
        if customer.lower() in q:
            return [
                row for row in rows
                if str(
                    row.get("customer", "")
                ).lower() == customer.lower()
            ]

    return rows


def apply_filters(rows, question):
    rows = filter_by_month(rows, question)
    rows = filter_by_region(rows, question)
    rows = filter_by_product(rows, question)
    rows = filter_by_customer(rows, question)

    return rows


# --------------------------------------------------
# METRIC HELPERS
# --------------------------------------------------

def is_paid(row):
    return str(
        row.get("status", "")
    ).lower() == "paid"


def is_refunded(row):
    return str(
        row.get("status", "")
    ).lower() == "refunded"


def total_revenue(rows, currency):
    return sum(
        row_value(row, currency)
        for row in rows
        if is_paid(row)
    )


def total_refunds(rows, currency):
    return sum(
        row_value(row, currency)
        for row in rows
        if is_refunded(row)
    )


# --------------------------------------------------
# PRODUCT QUESTIONS
# --------------------------------------------------

def answer_product_question(rows, question):
    q = question.lower()

    # Product -> revenue
    if (
        "revenue" in q
        or "sales" in q
        or "generated" in q
    ):
        revenue = defaultdict(float)

        for row in rows:
            if is_paid(row):
                product = row.get("product")

                if product:
                    revenue[product] += row_value(
                        row,
                        get_target_currency(question)
                    )

        if not revenue:
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
                revenue,
                key=revenue.get
            )

        return max(
            revenue,
            key=revenue.get
        )

    # Product -> quantity / units
    if any(
        phrase in q
        for phrase in [
            "quantity",
            "units",
            "unit",
            "sold",
            "most sold",
            "least sold"
        ]
    ):
        quantities = defaultdict(int)

        for row in rows:
            product = row.get("product")

            if product:
                quantities[product] += int(
                    row.get("qty", 0)
                )

        if not quantities:
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
                quantities,
                key=quantities.get
            )

        return max(
            quantities,
            key=quantities.get
        )

    # Product -> number of orders
    if (
        "order" in q
        or "orders" in q
    ):
        counts = defaultdict(int)

        for row in rows:
            product = row.get("product")

            if product:
                counts[product] += 1

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


# --------------------------------------------------
# CUSTOMER QUESTIONS
# --------------------------------------------------

def answer_customer_question(rows, question):
    q = question.lower()

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


# --------------------------------------------------
# MAIN QUESTION HANDLER
# --------------------------------------------------

def answer_question(question):
    q = str(question).strip().lower()

    rows = load_orders()

    # Product questions
    if (
        "product" in q
        or "item" in q
        or "which product" in q
        or "which item" in q
    ):
        return answer_product_question(
            apply_filters(rows, q),
            q
        )

    # Customer questions
    if (
        "customer" in q
        or "client" in q
        or re.search(r"\bc\d{3,}\b", q)
    ):
        return answer_customer_question(
            apply_filters(rows, q),
            q
        )

    # Refund questions
    if (
        "refund" in q
        or "refunded" in q
    ):
        rows = apply_filters(rows, q)

        currency = get_target_currency(q)

        total = total_refunds(
            rows,
            currency
        )

        return f"{total:.2f}"

    # Revenue questions
    if (
        "revenue" in q
        or "sales" in q
        or "income" in q
    ):
        rows = apply_filters(rows, q)

        currency = get_target_currency(q)

        total = total_revenue(
            rows,
            currency
        )

        return f"{total:.2f}"

    return "Unable to answer the question."


# --------------------------------------------------
# HTTP ENDPOINT
# --------------------------------------------------

@app.get("/")
def health():
    return {
        "status": "ok"
    }


@app.post("/")
def question():
    data = request.get_json()

    if not data or "question" not in data:
        return jsonify({
            "answer": "Missing question"
        }), 400

    try:
        answer = answer_question(
            data["question"]
        )

        return jsonify({
            "answer": answer
        })

    except Exception as e:
        print("ERROR:", repr(e))

        return jsonify({
            "answer": "Unable to answer the question."
        }), 500


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8891
    )
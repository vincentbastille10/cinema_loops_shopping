import os
import json
import stripe
import smtplib
from email.message import EmailMessage
from flask import Flask, render_template, request, jsonify, abort, url_for

app = Flask(__name__)

# ---------- STRIPE CONFIG ----------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# ---------- EMAIL CONFIG ----------
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")

# ---------- CLOUDFLARE ----------
CLOUDFLARE_BASE_URL = os.getenv("CLOUDFLARE_BASE_URL", "https://XXXX.r2.dev/spectra-media-loops")

# ---------- LOAD LOOPS FROM JSON CONFIG ----------
def load_loops():
    config_path = os.path.join(os.path.dirname(__file__), "loops.json")
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    categories = []
    all_loops_by_id = {}

    for cat in data.get("categories", []):
        cat_id = cat.get("id")
        title = cat.get("title")
        description = cat.get("description", "")
        folder = cat.get("folder", "")
        price_eur = cat.get("price_eur", 1)

        loops = []
        for filename in cat.get("files", []):
            base = os.path.splitext(filename)[0]
            loop_id = f"{cat_id}__{base}"
            # Nom lisible: cinema_loop_1 -> Cinema loop 1
            pretty_name = base.replace("_", " ").replace("  ", " ")
            url = f"{CLOUDFLARE_BASE_URL}/{folder}/{filename}"
            preview = f"/static/previews/{base}.mp3"

            loop = {
                "id": loop_id,
                "file": filename,
                "name": pretty_name,
                "url": url,
                "preview": preview,
                "price_eur": price_eur,
                "category_id": cat_id,
            }
            loops.append(loop)
            all_loops_by_id[loop_id] = loop

        categories.append(
            {
                "id": cat_id,
                "title": title,
                "description": description,
                "loops": loops,
            }
        )

    return categories, all_loops_by_id

CATEGORIES, ALL_LOOPS_BY_ID = load_loops()


@app.route("/")
def index():
    status = request.args.get("status")
    return render_template(
        "index.html",
        categories=CATEGORIES,
        stripe_public_key=STRIPE_PUBLIC_KEY,
        status=status,
    )


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    data = request.get_json() or {}
    selected_ids = data.get("loops", [])

    selected = [ALL_LOOPS_BY_ID[i] for i in selected_ids if i in ALL_LOOPS_BY_ID]

    if not selected:
        return jsonify({"error": "Aucune boucle sélectionnée."}), 400

    total_eur = sum(loop["price_eur"] for loop in selected)
    amount_cents = int(total_eur * 100)

    loops_str = ",".join(loop["id"] for loop in selected)

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=url_for("index", status="success", _external=True),
            cancel_url=url_for("index", status="cancel", _external=True),
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "eur",
                        "unit_amount": amount_cents,
                        "product_data": {
                            "name": "Spectra Film Loops",
                            "description": f"{len(selected)} boucles cinéma & horreur",
                        },
                    },
                }
            ],
            metadata={
                "loops": loops_str,
            },
        )
        return jsonify({"id": session.id, "url": session.url})
    except Exception as e:
        return jsonify(error=str(e)), 500


def send_loops_email(to_email: str, loop_ids: list):
    selected = [ALL_LOOPS_BY_ID[i] for i in loop_ids if i in ALL_LOOPS_BY_ID]
    if not selected or not SMTP_USER or not SMTP_PASS:
        return

    msg = EmailMessage()
    msg["Subject"] = "Vos boucles Spectra Film Loops"
    msg["From"] = SMTP_USER
    msg["To"] = to_email

    lines = [
        "Merci pour votre achat de boucles Spectra Media 🎬",
        "",
        "Voici vos liens de téléchargement (WAV haute qualité) :",
        "",
    ]
    for loop in selected:
        lines.append(f"- {loop['name']} : {loop['url']}")
    lines.append("")
    lines.append("Bonne création musicale,")
    lines.append("Spectra Media")

    msg.set_content("\n".join(lines))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    if not STRIPE_WEBHOOK_SECRET:
        return abort(400)

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception:
        return abort(400)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email")
        metadata_loops = session.get("metadata", {}).get("loops", "")

        if customer_email and metadata_loops:
            loop_ids = [s for s in metadata_loops.split(",") if s]
            send_loops_email(customer_email, loop_ids)

    return "", 200

# ---------------------------------------------------------
# PANIER - API JSON pour localStorage
# ---------------------------------------------------------

from flask import send_from_directory

@app.route("/cart")
def cart_page():
    lang = request.args.get("lang", "fr")
    return render_template("cart.html", lang=lang, stripe_public_key=STRIPE_PUBLIC_KEY)


@app.route("/get-cart", methods=["POST"])
def get_cart():
    """
    Le front envoie une liste d'IDs en localStorage
    On renvoie les infos complètes des loops
    """
    data = request.get_json() or {}
    ids = data.get("ids", [])

    items = []
    total = 0

    for loop_id in ids:
        if loop_id in ALL_LOOPS_BY_ID:
            loop = ALL_LOOPS_BY_ID[loop_id]
            items.append(loop)
            total += loop["price_eur"]

    return jsonify({
        "items": items,
        "total": total
    })


@app.route("/create-checkout-session-cart", methods=["POST"])
def create_checkout_session_cart():
    """
    Checkout basé sur le contenu du panier
    """
    data = request.get_json() or {}
    ids = data.get("ids", [])

    items = []
    total = 0

    for loop_id in ids:
        if loop_id in ALL_LOOPS_BY_ID:
            loop = ALL_LOOPS_BY_ID[loop_id]
            items.append(loop)
            total += loop["price_eur"]

    if not items:
        return jsonify({"error": "Panier vide."}), 400

    amount_cents = int(total * 100)
    loops_str = ",".join([item["id"] for item in items])

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=url_for("index", status="success", _external=True),
            cancel_url=url_for("index", status="cancel", _external=True),
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "eur",
                        "unit_amount": amount_cents,
                        "product_data": {
                            "name": "Spectra Film Loops (Panier)",
                            "description": f"{len(items)} boucles achetées",
                        },
                    },
                }
            ],
            metadata={"loops": loops_str},
        )

        return jsonify({"url": session.url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)

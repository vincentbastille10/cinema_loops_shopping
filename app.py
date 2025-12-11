import os
import json
import stripe
import requests
from flask import Flask, render_template, request, jsonify, abort, url_for

app = Flask(__name__)

# ---------- STRIPE CONFIG ----------
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Price pour le FULL PACK (99€)
FULL_PACK_PRICE_ID = os.getenv(
    "STRIPE_FULL_PACK_PRICE_ID",
    "price_1ScljP0fgdZf5PoKwAQkfcuw"  # ton price à 99€
)

# ---------- MAILJET API CONFIG ----------
MJ_API_KEY = os.getenv("MJ_API_KEY")
MJ_API_SECRET = os.getenv("MJ_API_SECRET")
MJ_FROM_EMAIL = os.getenv("MJ_FROM_EMAIL")
MJ_FROM_NAME = os.getenv("MJ_FROM_NAME", "Spectra Media Sounds")

# ---------- CLOUDFLARE ----------
CLOUDFLARE_BASE_URL = os.getenv(
    "CLOUDFLARE_BASE_URL",
    "https://XXXX.r2.cloudflarestorage.com"
)

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
            # Nom lisible: cinema_audio_1 -> cinema audio 1
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


# ---------------------------------------------------------
# ROUTES PAGES
# ---------------------------------------------------------

@app.route("/")
def index():
    status = request.args.get("status")
    lang = request.args.get("lang", "en")
    return render_template(
        "index.html",
        categories=CATEGORIES,
        stripe_public_key=STRIPE_PUBLIC_KEY,
        status=status,
        lang=lang,
    )


@app.route("/about")
def about_page():
    lang = request.args.get("lang", "en")
    return render_template("about.html", lang=lang)


# ---------------------------------------------------------
# CHECKOUT FULL PACK (99€ – TOUT LE CATALOGUE)
# ---------------------------------------------------------

@app.route("/create-fullpack-checkout", methods=["POST"])
def create_fullpack_checkout():
    """
    Crée une session Stripe pour le pack complet à 99€.
    TOUS les loops connus dans ALL_LOOPS_BY_ID sont envoyés par mail après paiement.
    """
    all_ids = list(ALL_LOOPS_BY_ID.keys())
    if not all_ids:
        return jsonify({"error": "Aucun loop configuré."}), 400

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=url_for("index", status="success", _external=True),
            cancel_url=url_for("index", status="cancel", _external=True),
            line_items=[
                {
                    "price": FULL_PACK_PRICE_ID,
                    "quantity": 1,
                }
            ],
            # 🔹 On n'envoie plus la liste complète des loops à Stripe
            metadata={
                "full_pack": "1",
            },
        )
        return jsonify({"url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



#  ALIAS pour compatibilité avec l'ancien JS
@app.route("/create-full-pack-session", methods=["POST"])
def create_full_pack_session():
    # On réutilise la logique existante sans dupliquer le code
    return create_fullpack_checkout()


# ---------------------------------------------------------
# CHECKOUT DIRECT (bouton "Buy this loop")
# ---------------------------------------------------------

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
                            "description": f"{len(selected)} cinema & horror loops",
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


# ---------------------------------------------------------
# ENVOI DES EMAILS AVEC MAILJET API
# ---------------------------------------------------------

def send_loops_email(to_email: str, loop_ids: list):
    """
    Envoie un email via l’API Mailjet avec les liens Cloudflare des loops achetées.
    """
    selected = [ALL_LOOPS_BY_ID[i] for i in loop_ids if i in ALL_LOOPS_BY_ID]

    if not selected:
        return

    if not (MJ_API_KEY and MJ_API_SECRET and MJ_FROM_EMAIL):
        # Pas de config Mailjet -> on sort silencieusement
        return

    # Corps du mail (texte)
    lines = [
        "Thank you for your purchase of Spectra Media loops 🎬",
        "",
        "Here are your download links (HD WAV):",
        "",
    ]
    for loop in selected:
        lines.append(f"- {loop['file']} : {loop['url']}")
    lines.append("")
    lines.append("Happy creating,")
    lines.append("Spectra Media Sounds")

    text_body = "\n".join(lines)

    payload = {
        "Messages": [
            {
                "From": {
                    "Email": MJ_FROM_EMAIL,
                    "Name": MJ_FROM_NAME,
                },
                "To": [
                    {
                        "Email": to_email,
                    }
                ],
                "Subject": "Your Spectra Media loops (download links)",
                "TextPart": text_body,
            }
        ]
    }

    try:
        resp = requests.post(
            "https://api.mailjet.com/v3.1/send",
            auth=(MJ_API_KEY, MJ_API_SECRET),
            json=payload,
            timeout=10,
        )
        # print("Mailjet status:", resp.status_code, resp.text)
    except Exception:
        # On ne plante pas le webhook Stripe si l’email a un souci
        pass


# ---------------------------------------------------------
# WEBHOOK STRIPE
# ---------------------------------------------------------

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
        metadata = session.get("metadata", {}) or {}

        loop_ids = []

        # 🔹 Cas FULL PACK
        if metadata.get("full_pack") == "1":
            loop_ids = list(ALL_LOOPS_BY_ID.keys())
        else:
            # 🔹 Cas achat à l'unité / panier
            metadata_loops = metadata.get("loops", "")
            if metadata_loops:
                loop_ids = [s for s in metadata_loops.split(",") if s]

        if customer_email and loop_ids:
            send_loops_email(customer_email, loop_ids)


    return "", 200


# ---------------------------------------------------------
# PANIER / API JSON (localStorage)
# ---------------------------------------------------------

@app.route("/cart")
def cart_page():
    lang = request.args.get("lang", "en")
    return render_template("cart.html", lang=lang, stripe_public_key=STRIPE_PUBLIC_KEY)


@app.route("/get-cart", methods=["POST"])
def get_cart():
    """
    Le front envoie une liste d'IDs stockés en localStorage.
    On renvoie les infos complètes des loops + total.
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

    return jsonify({"items": items, "total": total})


@app.route("/create-checkout-session-cart", methods=["POST"])
def create_checkout_session_cart():
    """
    Checkout basé sur le contenu du panier (page /cart).
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
                            "name": "Spectra Film Loops (Cart)",
                            "description": f"{len(items)} loops purchased",
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

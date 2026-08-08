"""Seed database with admin, technicians, and pest-control services."""
from getpass import getpass

from extensions import db
from models import User, Service


SERVICES = [
    {
        "name": "Termite Control",
        "slug": "termite-control",
        "short_description": "Complete termite elimination and wood protection.",
        "description": (
            "Termites silently destroy wooden structures, furniture, and fixtures. "
            "Our treatment combines pre- and post-construction soil barriers, "
            "wood treatments, and bait systems to eliminate colonies and prevent re-entry."
        ),
        "benefits": (
            "- Protects structural wood for years\n"
            "- Safe for children and pets\n"
            "- Long-term colony elimination\n"
            "- Odourless treatment options"
        ),
        "process": (
            "1. Site inspection and species identification\n"
            "2. Drilling and injection at active points\n"
            "3. Soil barrier treatment around perimeter\n"
            "4. Wood surface treatment\n"
            "5. Quality check and warranty card"
        ),
        "faq": (
            "Q: How long does the treatment last?\n"
            "A: Up to 5 years with warranty coverage.\n\n"
            "Q: Is it safe for kids and pets?\n"
            "A: Yes - we use odourless, low-toxicity formulations.\n\n"
            "Q: Do I need to vacate the premises?\n"
            "A: No, you can usually stay during treatment."
        ),
        "icon": "bi-bug-fill",
    },
    {
        "name": "Cockroach Control",
        "slug": "cockroach-control",
        "short_description": "Hygienic cockroach elimination from kitchens and washrooms.",
        "description": (
            "Cockroaches spread disease and trigger allergies. Our gel-bait + "
            "residual spray programme targets hiding spots and breeding zones "
            "for lasting relief."
        ),
        "benefits": (
            "- Eliminates German & American cockroaches\n"
            "- Kitchen-safe gel bait application\n"
            "- Long residual protection\n"
            "- Discreet, no foul smell"
        ),
        "process": (
            "1. Inspection of infestation zones\n"
            "2. Crack/crevice and void treatment\n"
            "3. Gel bait placement in kitchens\n"
            "4. External perimeter spray\n"
            "5. Monitoring and follow-up"
        ),
        "faq": (
            "Q: Is the gel bait safe near food?\n"
            "A: Yes - placed in inaccessible corners, away from food contact.\n\n"
            "Q: How many visits are needed?\n"
            "A: Typically 2-3 visits depending on infestation."
        ),
        "icon": "bi-bug",
    },
    {
        "name": "Mosquito Control",
        "slug": "mosquito-control",
        "short_description": "Outdoor and indoor mosquito treatment for dengue-free homes.",
        "description": (
            "Our mosquito control service combines larvicide application, "
            "fogging, and residual sprays to break the breeding cycle and "
            "keep outdoor spaces comfortable."
        ),
        "benefits": (
            "- Reduces dengue/malaria risk\n"
            "- Garden-safe formulations\n"
            "- Larvae source reduction\n"
            "- Comfortable outdoor evenings"
        ),
        "process": (
            "1. Identify breeding sources\n"
            "2. Larvicide application to stagnant water\n"
            "3. Outdoor fogging at dawn/dusk\n"
            "4. Indoor residual spray\n"
            "5. Source-reduction recommendations"
        ),
        "faq": (
            "Q: Is the spray harmful to plants?\n"
            "A: No - we use plant-safe formulations.\n\n"
            "Q: How often should it be done?\n"
            "A: Monthly during monsoon, quarterly otherwise."
        ),
        "icon": "bi-bug",
    },
    {
        "name": "Rodent Control",
        "slug": "rodent-control",
        "short_description": "Strategic rat and mouse control with trapping and sealing.",
        "description": (
            "Rats and mice damage property and spread disease. Our rodent "
            "programme uses bait stations, snap traps, and entry-point "
            "sealing for a complete solution."
        ),
        "benefits": (
            "- Tamper-proof bait stations\n"
            "- Entry-point sealing advice\n"
            "- Hygiene-focused approach\n"
            "- Pet-safe placement"
        ),
        "process": (
            "1. Inspection of droppings and tracks\n"
            "2. Placement of bait stations\n"
            "3. Snap traps along runways\n"
            "4. Entry-point identification\n"
            "5. Follow-up monitoring"
        ),
        "faq": (
            "Q: Are the chemicals safe for pets?\n"
            "A: Yes - bait placed in secured, pet-resistant stations.\n\n"
            "Q: How fast will I see results?\n"
            "A: Most infestations clear in 7-14 days."
        ),
        "icon": "bi-mouse",
    },
    {
        "name": "Bed Bug Control",
        "slug": "bed-bug-control",
        "short_description": "Deep mattress and room treatment for bed-bug elimination.",
        "description": (
            "Bed bugs cause itchy bites and sleepless nights. We use a "
            "combination of heat treatment, residual spray, and mattress "
            "encasement recommendations to fully eliminate them."
        ),
        "benefits": (
            "- Mattress-safe treatment\n"
            "- Multi-room coverage\n"
            "- Anti-re-infestation guidance\n"
            "- Discreet service"
        ),
        "process": (
            "1. Room-by-room inspection\n"
            "2. Residual spray on seams and cracks\n"
            "3. Mattress steam/heat treatment\n"
            "4. Frame and headboard treatment\n"
            "5. 14-day follow-up inspection"
        ),
        "faq": (
            "Q: Do I need to throw my mattress away?\n"
            "A: Usually no - treatment is sufficient in 95% of cases.\n\n"
            "Q: How many treatments are needed?\n"
            "A: Typically 2 treatments 14 days apart."
        ),
        "icon": "bi-bug",
    },
    {
        "name": "Commercial Pest Control",
        "slug": "commercial-pest-control",
        "short_description": "AMC-based pest management for offices, hotels, restaurants.",
        "description": (
            "Annual Maintenance Contracts covering restaurants, hotels, "
            "warehouses, and offices. Scheduled inspections, treatment, "
            "and detailed compliance reports."
        ),
        "benefits": (
            "- FSSAI / audit-ready reports\n"
            "- Scheduled monthly visits\n"
            "- Multi-site coverage\n"
            "- Priority response"
        ),
        "process": (
            "1. Site survey and risk mapping\n"
            "2. Tailored AMC plan and quote\n"
            "3. Monthly scheduled visits\n"
            "4. Digital reports after each visit\n"
            "5. Annual compliance review"
        ),
        "faq": (
            "Q: Do you provide service reports?\n"
            "A: Yes - digital PDF after each visit.\n\n"
            "Q: What's the minimum contract term?\n"
            "A: 12 months, with quarterly reviews."
        ),
        "icon": "bi-building",
    },
]


def run_seed(app, admin_email=None, admin_password=None):
    """Create admin, technicians, and services if they don't already exist."""
    with app.app_context():
        db.create_all()

        # ----- Admin -----
        if admin_email is None:
            admin_email = input("Admin email [admin@onestep.local]: ").strip() or "admin@onestep.local"
        if admin_password is None:
            try:
                admin_password = getpass("Admin password [Admin@123]: ") or "Admin@123"
            except Exception:
                admin_password = "Admin@123"

        if not User.query.filter_by(email=admin_email.lower()).first():
            admin = User(
                name="Admin",
                email=admin_email.lower(),
                role="ADMIN",
                is_active=True,
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            print(f"  + Admin user created: {admin_email}")
        else:
            print(f"  . Admin already exists: {admin_email}")

        # ----- Technicians -----
        sample_techs = [
            ("Ravi Kumar", "ravi@onestep.local", "Tech@123"),
            ("Suresh Patil", "suresh@onestep.local", "Tech@123"),
        ]
        for name, email, pw in sample_techs:
            if not User.query.filter_by(email=email.lower()).first():
                t = User(name=name, email=email.lower(), role="TECHNICIAN", is_active=True)
                t.set_password(pw)
                db.session.add(t)
                print(f"  + Technician created: {email} / {pw}")
            else:
                print(f"  . Technician exists: {email}")

        # ----- Services -----
        for spec in SERVICES:
            if not Service.query.filter_by(slug=spec["slug"]).first():
                s = Service(status="ACTIVE", **spec)
                db.session.add(s)
                print(f"  + Service: {spec['name']}")
            else:
                print(f"  . Service exists: {spec['name']}")

        db.session.commit()
        print("\nSeed complete.")
        print(f"  Admin login : {admin_email} / {admin_password}")
        print("  Tech logins : ravi@onestep.local / Tech@123")
        print("                 suresh@onestep.local / Tech@123")

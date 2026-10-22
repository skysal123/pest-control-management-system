"""Central catalogue of every service/product the business offers.

Single source of truth used by:
  * seed.py        -> ensures a Service row exists for each offering
  * blueprints     -> groups DB services into category optgroups for forms

`aliases` lets a catalogue entry match a legacy Service slug that already
exists in the database (so we never create duplicates).
"""

PEST_CONTROL = "Pest Control"
CLEANING = "Cleaning Services"
NETTING = "Bird Netting"

CATEGORIES = [PEST_CONTROL, CLEANING, NETTING]

CATALOG = [
    # ---------------- Pest Control ----------------
    {"name": "Ant Management", "slug": "ant-management", "category": PEST_CONTROL,
     "icon": "bi-bug",
     "short_description": "Targeted gel and spray treatments that eliminate ant colonies at the source."},
    {"name": "Bed Bug Management", "slug": "bed-bug-management", "category": PEST_CONTROL,
     "icon": "bi-bug", "aliases": ["bed-bug-control"],
     "short_description": "Discreet heat and chemical treatments that eradicate bed bugs from furniture and upholstery."},
    {"name": "Cockroach Management", "slug": "cockroach-management", "category": PEST_CONTROL,
     "icon": "bi-bug", "aliases": ["cockroach-control"],
     "short_description": "Advanced gel baits and surface sprays that wipe out cockroaches and stop breeding."},
    {"name": "Fly Management", "slug": "fly-management", "category": PEST_CONTROL,
     "icon": "bi-bug",
     "short_description": "Traps, misting and residual treatments to control flying insects indoors and out."},
    {"name": "Lizard Management", "slug": "lizard-management", "category": PEST_CONTROL,
     "icon": "bi-bug",
     "short_description": "Safe repellent treatments that drive lizards out of living and work areas."},
    {"name": "Mosquito Management", "slug": "mosquito-management", "category": PEST_CONTROL,
     "icon": "bi-bug", "aliases": ["mosquito-control"],
     "short_description": "Larviciding and fogging that breaks the mosquito breeding cycle and prevents disease."},
    {"name": "Prophylactic Treatment", "slug": "prophylactic-treatment", "category": PEST_CONTROL,
     "icon": "bi-shield-check",
     "short_description": "Preventive barrier treatment for new and renovated properties."},
    {"name": "Termite Treatment", "slug": "termite-treatment", "category": PEST_CONTROL,
     "icon": "bi-bug-fill", "aliases": ["termite-control"],
     "short_description": "Anti-termite soil treatment and wall injection that protects your structure."},
    {"name": "Rodent Management", "slug": "rodent-management", "category": PEST_CONTROL,
     "icon": "bi-mouse", "aliases": ["rodent-control"],
     "short_description": "Baiting, trapping and proofing that removes rats and mice and seals entry points."},
    {"name": "Spider Management", "slug": "spider-management", "category": PEST_CONTROL,
     "icon": "bi-bug",
     "short_description": "Cobweb removal and residual treatment to keep webs and spiders away."},
    {"name": "Wood Borer Management", "slug": "wood-borer-management", "category": PEST_CONTROL,
     "icon": "bi-bug",
     "short_description": "Targeted treatment that eliminates wood borers and protects wooden fixtures."},
    {"name": "Commercial Pest Control", "slug": "commercial-pest-control", "category": PEST_CONTROL,
     "icon": "bi-building",
     "short_description": "AMC-based pest management for offices, hotels, restaurants and warehouses."},
    # ---------------- Cleaning ----------------
    {"name": "Commercial Cleaning", "slug": "commercial-cleaning", "category": CLEANING,
     "icon": "bi-building",
     "short_description": "End-to-end cleaning for offices, gyms, restaurants and event venues."},
    {"name": "Industrial Cleaning", "slug": "industrial-cleaning", "category": CLEANING,
     "icon": "bi-factory",
     "short_description": "Heavy-duty cleaning of machinery, tanks and plants with safety-first crews."},
    {"name": "Society Cleaning", "slug": "society-cleaning", "category": CLEANING,
     "icon": "bi-houses",
     "short_description": "Complete housekeeping for corridors, terraces and gardens of residential societies."},
    {"name": "House Cleaning", "slug": "house-cleaning", "category": CLEANING,
     "icon": "bi-house-heart",
     "short_description": "Deep home cleaning covering rooms, carpets, upholstery and floor polishing."},
    {"name": "Water Tank Cleaning", "slug": "water-tank-cleaning", "category": CLEANING,
     "icon": "bi-droplet",
     "short_description": "Sludge and algae removal by vetted professionals to keep stored water pure."},
    # ---------------- Bird Netting ----------------
    {"name": "Society Bird Netting", "slug": "society-bird-netting", "category": NETTING,
     "icon": "bi-grid-3x3-gap",
     "short_description": "Full-coverage netting for society balconies, terraces and common areas."},
    {"name": "Industrial Bird Netting", "slug": "industrial-bird-netting", "category": NETTING,
     "icon": "bi-grid-3x3-gap",
     "short_description": "Heavy-duty netting for warehouses, factories and industrial sheds."},
    {"name": "Residential Bird Netting", "slug": "residential-bird-netting", "category": NETTING,
     "icon": "bi-grid-3x3-gap",
     "short_description": "Discreet, durable netting for homes and apartments to keep balconies bird-free."},
]

OTHER = "Other Services"


def catalog_item_for_slug(slug):
    """Return the catalogue entry matching a Service slug (incl. legacy aliases)."""
    for item in CATALOG:
        if slug == item["slug"] or slug in item.get("aliases", []):
            return item
    return None


def category_for_slug(slug):
    """Return the catalogue category for a Service slug (falls back to Other)."""
    item = catalog_item_for_slug(slug)
    return item["category"] if item else OTHER


def group_services(services):
    """Group a list of Service rows into an ordered {category: [services]} dict."""
    groups = {c: [] for c in CATEGORIES}
    groups[OTHER] = []
    for svc in services:
        groups[category_for_slug(svc.slug)].append(svc)
    return {c: items for c, items in groups.items() if items}


def group_services_map(services):
    """Group services into {category: [{"id","name","slug","match"}]} for the UI picker."""
    groups = {c: [] for c in CATEGORIES}
    groups[OTHER] = []
    for svc in services:
        item = catalog_item_for_slug(svc.slug)
        match = [svc.slug]
        if item:
            match.append(item["slug"])
            match.extend(item.get("aliases", []))
        groups[category_for_slug(svc.slug)].append(
            {
                "id": svc.id,
                "name": svc.name,
                "slug": svc.slug,
                "match": sorted(set(match)),
            }
        )
    return {c: items for c, items in groups.items() if items}

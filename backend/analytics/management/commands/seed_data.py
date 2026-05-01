import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from analytics.models import Sale


class Command(BaseCommand):
    help = "Seeds the database with mock sales data"

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding data...")
        Sale.objects.all().delete()

        products = [
            ("Laptop Pro", "Electronics", 1500.00),
            ("Wireless Mouse", "Electronics", 25.00),
            ("Ergonomic Keyboard", "Electronics", 80.00),
            ("Office Chair", "Furniture", 200.00),
            ("Standing Desk", "Furniture", 400.00),
        ]

        start_date = date(2023, 1, 1)
        sales = []
        for i in range(100):
            product_name, category, price = random.choice(products)
            qty = random.randint(1, 5)
            revenue = qty * price
            # Random date within the last year
            sale_date = start_date + timedelta(days=random.randint(0, 365))

            sales.append(
                Sale(
                    product_name=product_name,
                    category=category,
                    quantity=qty,
                    revenue=revenue,
                    sale_date=sale_date,
                )
            )

        Sale.objects.bulk_create(sales)
        self.stdout.write(
            self.style.SUCCESS(f"Successfully seeded {{len(sales)}} sales records!")
        )

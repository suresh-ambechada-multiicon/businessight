import os
import django
import sys

sys.path.append('/home/suresh/dev/BusinessdataSight/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessSight.settings')
django.setup()

from sqlalchemy import create_engine, inspect

db_uri = "postgresql+psycopg2://postgres:1475@localhost:5432/business"
engine = create_engine(db_uri)
inspector = inspect(engine)

all_tables = inspector.get_table_names(schema=None)
print(f"Total tables found: {len(all_tables)}")
print(all_tables[:15])

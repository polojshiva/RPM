"""
Stage 0: Database Schema Introspection
Connects to database and queries information_schema to verify actual table structures
"""
import os
import sys
from pathlib import Path
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://user:password@localhost:5432/wiser_ops")

def get_table_info(engine: Engine, schema: str, table_name: str) -> dict:
    """Get detailed table information from information_schema"""
    inspector = inspect(engine)
    
    info = {
        'schema': schema,
        'table_name': table_name,
        'exists': False,
        'columns': [],
        'primary_keys': [],
        'foreign_keys': [],
        'indexes': [],
        'constraints': []
    }
    
    try:
        # Check if table exists
        if inspector.has_table(table_name, schema=schema):
            info['exists'] = True
            
            # Get columns
            columns = inspector.get_columns(table_name, schema=schema)
            for col in columns:
                info['columns'].append({
                    'name': col['name'],
                    'type': str(col['type']),
                    'nullable': col['nullable'],
                    'default': str(col.get('default', '')),
                    'autoincrement': col.get('autoincrement', False)
                })
            
            # Get primary keys
            pk_constraint = inspector.get_pk_constraint(table_name, schema=schema)
            if pk_constraint and pk_constraint.get('constrained_columns'):
                info['primary_keys'] = pk_constraint['constrained_columns']
            
            # Get foreign keys
            fks = inspector.get_foreign_keys(table_name, schema=schema)
            for fk in fks:
                info['foreign_keys'].append({
                    'name': fk.get('name', ''),
                    'constrained_columns': fk['constrained_columns'],
                    'referred_schema': fk.get('referred_schema', ''),
                    'referred_table': fk['referred_table'],
                    'referred_columns': fk['referred_columns']
                })
            
            # Get indexes
            indexes = inspector.get_indexes(table_name, schema=schema)
            for idx in indexes:
                info['indexes'].append({
                    'name': idx['name'],
                    'columns': idx['column_names'],
                    'unique': idx.get('unique', False)
                })
            
            # Get check constraints and unique constraints
            with engine.connect() as conn:
                # Check constraints
                check_query = text("""
                    SELECT conname, pg_get_constraintdef(oid) as definition
                    FROM pg_constraint
                    WHERE conrelid = :table_oid
                    AND contype = 'c'
                """)
                
                # Get table OID
                oid_query = text("""
                    SELECT oid FROM pg_class
                    WHERE relname = :table_name
                    AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = :schema)
                """)
                
                result = conn.execute(oid_query, {'table_name': table_name, 'schema': schema})
                oid_row = result.fetchone()
                
                if oid_row:
                    table_oid = oid_row[0]
                    result = conn.execute(check_query, {'table_oid': table_oid})
                    for row in result:
                        info['constraints'].append({
                            'name': row[0],
                            'type': 'CHECK',
                            'definition': row[1]
                        })
                
                # Unique constraints
                unique_query = text("""
                    SELECT conname, pg_get_constraintdef(oid) as definition
                    FROM pg_constraint
                    WHERE conrelid = :table_oid
                    AND contype = 'u'
                """)
                
                if oid_row:
                    result = conn.execute(unique_query, {'table_oid': table_oid})
                    for row in result:
                        info['constraints'].append({
                            'name': row[0],
                            'type': 'UNIQUE',
                            'definition': row[1]
                        })
    except Exception as e:
        info['error'] = str(e)
    
    return info

def main():
    """Main introspection function"""
    print("=" * 80)
    print("Stage 0: Database Schema Introspection")
    print("=" * 80)
    print()
    
    try:
        engine = create_engine(DATABASE_URL, echo=False)
        
        # Tables to inspect
        tables_to_check = [
            ('integration', 'send_serviceops'),
            ('integration', 'integration_receive_serviceops'),
            ('service_ops', 'integration_inbox'),
            ('service_ops', 'packet'),
            ('service_ops', 'packet_document'),
            ('service_ops', 'packet_decision'),
            ('service_ops', 'send_clinicalops'),
            ('service_ops', 'send_serviceops'),  # Check if this exists as clinicalops inbox
        ]
        
        results = {}
        
        for schema, table_name in tables_to_check:
            print(f"Checking {schema}.{table_name}...")
            info = get_table_info(engine, schema, table_name)
            results[f"{schema}.{table_name}"] = info
            
            if info['exists']:
                print(f"  [EXISTS]")
                print(f"  Columns: {len(info['columns'])}")
                print(f"  Primary Keys: {info['primary_keys']}")
                print(f"  Foreign Keys: {len(info['foreign_keys'])}")
                print(f"  Indexes: {len(info['indexes'])}")
                print(f"  Constraints: {len(info['constraints'])}")
            else:
                print(f"  [DOES NOT EXIST]")
            print()
        
        # Generate markdown report
        report_path = Path(__file__).parent.parent / "STAGE_0_DB_SCHEMA_VERIFICATION.md"
        generate_markdown_report(results, report_path)
        
        print(f"Report generated: {report_path}")
        print()
        print("=" * 80)
        print("Introspection complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def generate_markdown_report(results: dict, output_path: Path):
    """Generate markdown report from introspection results"""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("# Stage 0: Database Schema Verification Report\n\n")
        f.write("**Generated:** Database introspection via SQLAlchemy\n\n")
        f.write("---\n\n")
        
        for table_key, info in results.items():
            schema, table_name = table_key.split('.')
            f.write(f"## {schema}.{table_name}\n\n")
            
            if not info.get('exists'):
                f.write("**Status:** DOES NOT EXIST\n\n")
                f.write("---\n\n")
                continue
            
            f.write("**Status:** EXISTS\n\n")
            
            # Columns
            f.write("### Columns\n\n")
            f.write("| Column Name | Type | Nullable | Default | Auto Increment |\n")
            f.write("|-------------|------|----------|---------|----------------|\n")
            for col in info['columns']:
                col_name = col['name']
                col_type = col['type'].replace('|', '\\|')
                nullable = 'YES' if col['nullable'] else 'NO'
                default = col['default'] or ''
                auto_inc = 'YES' if col['autoincrement'] else 'NO'
                f.write(f"| `{col_name}` | `{col_type}` | {nullable} | {default} | {auto_inc} |\n")
            f.write("\n")
            
            # Primary Keys
            if info['primary_keys']:
                f.write("### Primary Keys\n\n")
                f.write(f"- {', '.join([f'`{pk}`' for pk in info['primary_keys']])}\n\n")
            
            # Foreign Keys
            if info['foreign_keys']:
                f.write("### Foreign Keys\n\n")
                for fk in info['foreign_keys']:
                    f.write(f"- **{fk['name']}**: `{', '.join(fk['constrained_columns'])}` → ")
                    f.write(f"`{fk['referred_schema']}.{fk['referred_table']}({', '.join(fk['referred_columns'])})`\n")
                f.write("\n")
            
            # Indexes
            if info['indexes']:
                f.write("### Indexes\n\n")
                for idx in info['indexes']:
                    unique_str = "UNIQUE " if idx['unique'] else ""
                    # Filter out None values from columns
                    columns = [str(c) for c in idx['columns'] if c is not None]
                    f.write(f"- **{unique_str}{idx['name']}**: `{', '.join(columns)}`\n")
                f.write("\n")
            
            # Constraints
            if info['constraints']:
                f.write("### Constraints\n\n")
                for constraint in info['constraints']:
                    f.write(f"- **{constraint['name']}** ({constraint['type']}): `{constraint['definition']}`\n")
                f.write("\n")
            
            f.write("---\n\n")

if __name__ == "__main__":
    main()


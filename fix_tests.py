import os
import glob

for filepath in glob.glob("tests/*.py"):
    with open(filepath, "r") as f:
        content = f.read()
    
    if "app.dependency_overrides[get_db] = override_get_db" in content:
        # Remove the global override
        content = content.replace("app.dependency_overrides[get_db] = override_get_db\n", "")
        
        # Insert into setup_db
        if "def setup_db():\n    Base.metadata.create_all" in content:
            content = content.replace(
                "def setup_db():\n    Base.metadata.create_all",
                "def setup_db():\n    app.dependency_overrides[get_db] = override_get_db\n    Base.metadata.create_all"
            )
        elif "def setup_db():\n    app.dependency_overrides.clear()" not in content:
            # Just to be safe, if setup_db is different
            pass
            
        with open(filepath, "w") as f:
            f.write(content)


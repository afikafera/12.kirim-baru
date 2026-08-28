import os

def load_config():
    """Load config dari .env file"""
    config = {}
    with open(os.path.join(os.path.dirname(__file__), ".env")) as f:
        for line in f:
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                val = val.strip('"').strip("'")
                config[key] = val
                os.environ[key] = val
    return config

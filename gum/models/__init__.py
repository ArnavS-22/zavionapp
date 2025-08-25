# Re-export from the actual models.py file
import sys
import os
import importlib.util

# Load models.py from parent directory
_models_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models.py')
_spec = importlib.util.spec_from_file_location("gum_models", _models_path)
_models = importlib.util.module_from_spec(_spec)
sys.modules['gum_models'] = _models
_spec.loader.exec_module(_models)

# Re-export everything
observation_proposition = _models.observation_proposition
proposition_parent = _models.proposition_parent
Observation = _models.Observation
Proposition = _models.Proposition
Suggestion = _models.Suggestion
init_db = _models.init_db
Base = _models.Base

# Export all for * imports
__all__ = ['observation_proposition', 'proposition_parent', 'Observation', 'Proposition', 'Suggestion', 'init_db', 'Base']

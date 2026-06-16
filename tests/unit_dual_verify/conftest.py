import sys
from pathlib import Path
# 把 scripts 目录加进 path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
